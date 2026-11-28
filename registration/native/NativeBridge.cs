using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;
using System.Windows.Automation;
using System.Windows.Forms;
using System.Web.Script.Serialization;
using Microsoft.Win32;
using System.Globalization;
using System.Text.RegularExpressions;

public class NodeInfo {
    public int index, parent; public string name,id,type,text,value; public bool enabled,invoke; public string[] patterns;
    [ScriptIgnore] public AutomationElement element;
}
public class UiSnapshot {
    public bool ok=true; public string observedAt,url,text,lockState; public List<NodeInfo> nodes;
    public long readDurationMs;
}
public class NativeBridge : Form {
    Label status=new Label{Dock=DockStyle.Fill,Padding=new Padding(20),Text="原生连接已启动。仅执行控制台中明确安排的任务。"};
    string baseDir=AppDomain.CurrentDomain.BaseDirectory;
    string queueDir; volatile bool stopping=false; volatile string lockState="unobserved";
    readonly object activityLock=new object();
    string currentOperation="idle",operationStartedAt=null;
    JavaScriptSerializer json=new JavaScriptSerializer{MaxJsonLength=2000000};
    Process serverProcess;
    NotifyIcon tray; bool explicitExit=false;
    readonly object launchLock=new object();
    CheckBox autoIracing=new CheckBox{Text="启动时打开 iRacing",AutoSize=true,Checked=true};
    CheckBox autoTailscale=new CheckBox{Text="启动时打开 Tailscale",AutoSize=true,Checked=true};
    Label startupStatus=new Label{Dock=DockStyle.Top,Height=85,Padding=new Padding(12),Text="正在检查启动设置…"};
    public NativeBridge(){
        Text="iRacing 报名助手 · 原生连接"; Width=730; Height=340; Controls.Add(status);
        queueDir=Path.Combine(baseDir,"data","bridge"); Directory.CreateDirectory(queueDir);
        Controls.Add(startupStatus);
        var startupOptions=new FlowLayoutPanel{Dock=DockStyle.Top,Height=38,Padding=new Padding(10,4,0,0)};
        startupOptions.Controls.Add(autoIracing);startupOptions.Controls.Add(autoTailscale);Controls.Add(startupOptions);
        LoadStartupSettings();
        autoIracing.CheckedChanged+=(s,e)=>SaveStartupSettings();autoTailscale.CheckedChanged+=(s,e)=>SaveStartupSettings();
        var panel=new FlowLayoutPanel{Dock=DockStyle.Bottom,Height=45};
        var open=new Button{Text="打开控制台",Width=130};
        open.Click+=(s,e)=>{try{var key=File.ReadAllText(Path.Combine(baseDir,"data","access-token.txt")).Trim();Process.Start("http://127.0.0.1:19390/#key="+key);}catch{MessageBox.Show("控制台正在启动，请稍后再试。");}};
        panel.Controls.Add(open); Controls.Add(panel);
        var choose=new Button{Text="选择 iRacing 客户端",Width=180};
        choose.Click+=(s,e)=>{using(var dialog=new OpenFileDialog{Title="选择 iRacing 安装目录 ui 文件夹中的 iRacingUI.exe",Filter="iRacing 客户端|iRacingUI.exe",CheckFileExists=true}){if(dialog.ShowDialog()!=DialogResult.OK)return;if(!String.Equals(Path.GetFileName(dialog.FileName),"iRacingUI.exe",StringComparison.OrdinalIgnoreCase)){MessageBox.Show("请选择 iRacingUI.exe。");return;}Save(Path.Combine(baseDir,"data","iracing-settings.json"),new{path=dialog.FileName});status.Text="已保存客户端位置。请正常登录 iRacing，再到控制台检查连接。";}};
        panel.Controls.Add(choose);
        var exit=new Button{Text="退出并停止任务",Width=150};
        exit.Click+=(s,e)=>{explicitExit=true;Close();};panel.Controls.Add(exit);
        var menu=new ContextMenuStrip();
        menu.Items.Add("显示报名助手",null,(s,e)=>{Show();WindowState=FormWindowState.Normal;Activate();});
        menu.Items.Add("退出并停止任务",null,(s,e)=>{explicitExit=true;Close();});
        tray=new NotifyIcon{Icon=System.Drawing.SystemIcons.Application,Text="iRacing 报名助手 · 后台运行",Visible=true,ContextMenuStrip=menu};
        tray.DoubleClick+=(s,e)=>{Show();WindowState=FormWindowState.Normal;Activate();};
        SystemEvents.SessionSwitch += SessionChanged;
        FormClosing+=(s,e)=>{if(!explicitExit&&e.CloseReason==CloseReason.UserClosing){e.Cancel=true;Hide();tray.ShowBalloonTip(3000,"报名助手继续运行","关闭窗口会收进托盘；停止任务请点“退出并停止任务”。",ToolTipIcon.Info);return;}stopping=true;tray.Dispose();SystemEvents.SessionSwitch-=SessionChanged;try{if(serverProcess!=null&&!serverProcess.HasExited)serverProcess.Kill();}catch{}};
        Shown+=(s,e)=>{StartServer();var heartbeat=new Thread(Heartbeat){IsBackground=true};heartbeat.Start();var t=new Thread(Loop){IsBackground=true};t.SetApartmentState(ApartmentState.MTA);t.Start();bool ir=autoIracing.Checked,ts=autoTailscale.Checked;new Thread(()=>StartCompanions(ir,ts)){IsBackground=true}.Start();};
    }
    void LoadStartupSettings(){
        var path=Path.Combine(baseDir,"data","startup-settings.json");
        if(!File.Exists(path))return;
        try{var saved=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(path));
            object value;if(saved.TryGetValue("iracing",out value)&&value is bool)autoIracing.Checked=(bool)value;
            if(saved.TryGetValue("tailscale",out value)&&value is bool)autoTailscale.Checked=(bool)value;
        }catch{autoIracing.Checked=false;autoTailscale.Checked=false;status.Text="启动设置无法读取。请重新勾选需要自动打开的客户端，保存后下次启动生效。";}
    }
    void SaveStartupSettings(){
        try{Save(Path.Combine(baseDir,"data","startup-settings.json"),new{iracing=autoIracing.Checked,tailscale=autoTailscale.Checked});status.Text="已保存启动设置，下次启动助手时生效。关闭助手不会退出 iRacing 或 Tailscale。";}
        catch(Exception ex){status.Text="启动设置保存失败，请确认助手目录可写："+ex.Message;}
    }
    void UpdateStartupStatus(string message){if(!stopping)try{BeginInvoke((Action)(()=>startupStatus.Text=message));}catch{}}
    bool LaunchIracing(){
        lock(launchLock){
            if(Process.GetProcessesByName("iRacingUI").Length>0)return false;
            var path=IracingPath();
            if(path==null)throw new Exception("找不到客户端，请点“选择 iRacing 客户端”，选择 ui\\iRacingUI.exe 后重开助手。");
            Process.Start(new ProcessStartInfo(path){UseShellExecute=false,WorkingDirectory=Path.GetDirectoryName(path),WindowStyle=ProcessWindowStyle.Normal});
            Thread.Sleep(1200);
            if(Process.GetProcessesByName("iRacingUI").Length==0)throw new Exception("客户端未保持运行，请手动打开 iRacing 查看错误后重试。");
            return true;
        }
    }
    string LaunchTailscale(){
        if(Process.GetProcessesByName("tailscale-ipn").Length>0)return "已在运行（连接状态请在控制台检查）";
        string path=null;
        foreach(var folder in new[]{Environment.GetEnvironmentVariable("ProgramW6432"),Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86)}){
            if(String.IsNullOrEmpty(folder))continue;
            var candidate=Path.Combine(folder,"Tailscale","tailscale-ipn.exe");if(File.Exists(candidate)){path=candidate;break;}
        }
        if(path==null)throw new Exception("未找到 Tailscale，请先安装官方 Windows 客户端；仅在本机使用不需要它。");
        Process.Start(new ProcessStartInfo(path){UseShellExecute=false,WorkingDirectory=Path.GetDirectoryName(path),WindowStyle=ProcessWindowStyle.Normal});
        Thread.Sleep(1200);
        if(Process.GetProcessesByName("tailscale-ipn").Length==0)throw new Exception("客户端未保持运行，请从 Windows 开始菜单打开 Tailscale 检查。");
        return "已打开（可能收在右下角托盘；仍需登录并连接）";
    }
    void StartCompanions(bool iracing,bool tailscale){
        string ir="未启用自动打开",ts="未启用自动打开";
        UpdateStartupStatus("正在打开客户端，请稍候…");
        if(iracing)try{ir=LaunchIracing()?"已打开，等待登录和页面加载":"已在运行";}catch(Exception ex){ir="未启动："+ex.Message;}
        UpdateStartupStatus("iRacing："+ir+"\nTailscale：正在检查…");
        if(tailscale)try{ts=LaunchTailscale();}catch(Exception ex){ts="未启动："+ex.Message;}
        UpdateStartupStatus("iRacing："+ir+"\nTailscale："+ts+"\n打开控制台 → 检查运行条件，可核实登录和手机连接。");
    }
    void StartServer(){
        if(!File.Exists(Path.Combine(baseDir,"server.mjs"))){status.Text="程序文件缺失：找不到 server.mjs。请完整解压安装包，不要只复制 exe，然后重新启动。";return;}
        try{
            var node=Path.Combine(baseDir,"runtime","node","node.exe");
            var config=Path.Combine(baseDir,"runtime.json");
            if(File.Exists(config))node=(string)json.Deserialize<Dictionary<string,object>>(File.ReadAllText(config))["nodePath"];
            if(!Path.IsPathRooted(node))node=Path.GetFullPath(Path.Combine(baseDir,node));
            if(!File.Exists(node))throw new Exception("运行环境缺失。请完整解压安装包，不要只复制 exe；runtime\\node\\node.exe 必须存在。");
            var info=new ProcessStartInfo(node,"\""+Path.Combine(baseDir,"server.mjs")+"\""){UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden,WorkingDirectory=baseDir,RedirectStandardError=true,RedirectStandardOutput=true};
            serverProcess=new Process{StartInfo=info,EnableRaisingEvents=true};
            serverProcess.ErrorDataReceived+=(s,e)=>{if(e.Data!=null){try{var log=Path.Combine(baseDir,"data","server.log");Rotate(log);File.AppendAllText(log,DateTime.UtcNow.ToString("o")+" "+e.Data+Environment.NewLine);}catch{}}};
            serverProcess.OutputDataReceived+=(s,e)=>{};
            serverProcess.Exited+=(s,e)=>{if(!stopping){try{BeginInvoke((Action)(()=>status.Text="控制台启动失败或服务退出。先关闭重复助手；确认完整解压到可写文件夹，再重开。详细原因见 data/server.log（例如 EADDRINUSE 表示 19390 端口被占用）。"));}catch{}}};
            serverProcess.Start();serverProcess.BeginErrorReadLine();serverProcess.BeginOutputReadLine();
        }catch(Exception ex){status.Text="控制台启动失败："+ex.Message;}
    }
    void Rotate(string path){
        if(!File.Exists(path)||new FileInfo(path).Length<1048576)return;
        if(File.Exists(path+".3"))File.Delete(path+".3");
        for(int i=2;i>=1;i--)if(File.Exists(path+"."+i))File.Move(path+"."+i,path+"."+(i+1));
        File.Move(path,path+".1");
    }
    string IracingPath(){
        var config=Path.Combine(baseDir,"data","iracing-settings.json");
        if(File.Exists(config)){var saved=(string)json.Deserialize<Dictionary<string,object>>(File.ReadAllText(config))["path"];if(Path.GetFileName(saved).Equals("iRacingUI.exe",StringComparison.OrdinalIgnoreCase)&&File.Exists(saved))return saved;}
        foreach(var proc in Process.GetProcessesByName("iRacingUI")){try{return proc.MainModule.FileName;}catch{}}
        foreach(var drive in DriveInfo.GetDrives().Where(d=>d.IsReady&&d.DriveType==DriveType.Fixed))foreach(var relative in new[]{@"iRacing\ui\iRacingUI.exe",@"Program Files (x86)\iRacing\ui\iRacingUI.exe",@"Program Files\iRacing\ui\iRacingUI.exe",@"SteamLibrary\steamapps\common\iRacing\ui\iRacingUI.exe",@"Steam\steamapps\common\iRacing\ui\iRacingUI.exe"}){var path=Path.Combine(drive.RootDirectory.FullName,relative);if(File.Exists(path))return path;}
        return null;
    }
    void SessionChanged(object sender,SessionSwitchEventArgs e){
        if(e.Reason==SessionSwitchReason.SessionLock) lockState="locked";
        if(e.Reason==SessionSwitchReason.SessionUnlock) lockState="unlocked";
    }
    void Save(string path,object value){var tmp=path+".tmp";File.WriteAllText(tmp,new JavaScriptSerializer{MaxJsonLength=2000000}.Serialize(value));if(File.Exists(path))File.Replace(tmp,path,null);else File.Move(tmp,path);}
    void Heartbeat(){
        while(!stopping){
            try{string op,started;lock(activityLock){op=currentOperation;started=operationStartedAt;}
                Save(Path.Combine(queueDir,"heartbeat.json"),new{at=DateTime.UtcNow.ToString("o"),lockState=lockState,pid=Process.GetCurrentProcess().Id,operation=op,operationStartedAt=started});
            }catch{}Thread.Sleep(1000);
        }
    }
    void Diagnostic(string op,long elapsed,string result,string errorType){
        try{var path=Path.Combine(baseDir,"data","bridge-timing.jsonl");
            Rotate(path);
            File.AppendAllText(path,json.Serialize(new{at=DateTime.UtcNow.ToString("o"),operation=op,durationMs=elapsed,result=result,errorType=errorType,lockState=lockState})+Environment.NewLine);
        }catch{}
    }
    void Loop(){
        while(!stopping){
            try{
                foreach(var file in Directory.GetFiles(queueDir,"*.request.json")){
                    string id=Path.GetFileName(file).Replace(".request.json",""); Guid gid;
                    if(!Guid.TryParse(id,out gid))continue;
                    var claimed=Path.Combine(queueDir,id+".processing.json");
                    var watch=Stopwatch.StartNew();string operation="unknown",outcome="error",errorType=null;
                    try{
                        File.Move(file,claimed);
                        var request=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(claimed));
                        operation=(string)request["op"];
                        lock(activityLock){currentOperation=operation;operationStartedAt=DateTime.UtcNow.ToString("o");}
                        var deadline=DateTime.Parse((string)request["deadline"],null,System.Globalization.DateTimeStyles.RoundtripKind).ToUniversalTime();
                        if(DateTime.UtcNow>deadline)throw new Exception("请求已过期，未执行。");
                        var result=ExecuteRequest(request,deadline);
                        Save(Path.Combine(queueDir,id+".response.json"),new{ok=true,result=result});
                        outcome="ok";
                        if(!stopping)BeginInvoke((Action)(()=>status.Text="已完成："+request["op"]+"\n"+DateTime.Now.ToString("HH:mm:ss")));
                    }catch(Exception ex){
                        errorType=ex.GetType().Name;
                        var message=String.IsNullOrWhiteSpace(ex.Message)?"原生接口异常："+errorType:ex.Message;
                        Save(Path.Combine(queueDir,id+".response.json"),new{ok=false,error=message,errorType=errorType});
                        if(!stopping)BeginInvoke((Action)(()=>status.Text="操作已停止："+message));
                    }finally{Diagnostic(operation,watch.ElapsedMilliseconds,outcome,errorType);lock(activityLock){currentOperation="idle";operationStartedAt=null;}}
                }
            }catch{} Thread.Sleep(250);
        }
    }
    AutomationElement FindRoot(){
        var pids=new HashSet<int>(Process.GetProcessesByName("iRacingUI").Select(p=>p.Id));
        var roots=new List<AutomationElement>();
        foreach(AutomationElement w in AutomationElement.RootElement.FindAll(TreeScope.Children,Condition.TrueCondition)){
            try{if(pids.Contains(w.Current.ProcessId)&&w.Current.Name=="iRacing")roots.Add(w);}catch{}
        }
        if(roots.Count!=1)throw new Exception("请保持一个正常打开的 iRacing UI 窗口；当前找到 "+roots.Count+" 个。");
        return roots[0];
    }
    public UiSnapshot Read(){
        var watch=Stopwatch.StartNew();
        var root=FindRoot();
        object windowPattern;
        if(root.TryGetCurrentPattern(WindowPattern.Pattern,out windowPattern)){
            var window=(WindowPattern)windowPattern;
            if(window.Current.WindowVisualState==WindowVisualState.Minimized){
                window.SetWindowVisualState(WindowVisualState.Normal);
                Thread.Sleep(1400);
                root=FindRoot();
            }
        }
        var doc=root.FindFirst(TreeScope.Descendants,new PropertyCondition(AutomationElement.ControlTypeProperty,ControlType.Document));
        if(doc==null)throw new Exception("客户端没有暴露可读取的页面。");
        object v; string url="";
        if(doc.TryGetCurrentPattern(ValuePattern.Pattern,out v))url=((ValuePattern)v).Current.Value;
        Uri parsed;
        if(!Uri.TryCreate(url,UriKind.Absolute,out parsed)||parsed.Scheme!="https"||parsed.Host!="members-ng.iracing.com")throw new Exception("客户端尚未进入已登录的官方页面，请自行完成登录。");
        if(!doc.TryGetCurrentPattern(TextPattern.Pattern,out v))throw new Exception("客户端未提供页面文字。");
        var text=(TextPattern)v; var rows=new List<NodeInfo>(); Walk(doc,-1,rows,text,0);
        var content=text.DocumentRange.GetText(150000);
        return new UiSnapshot{observedAt=DateTime.UtcNow.ToString("o"),url=parsed.GetLeftPart(UriPartial.Path),text=content,nodes=rows,lockState=lockState,readDurationMs=watch.ElapsedMilliseconds};
    }
    void Walk(AutomationElement e,int parent,List<NodeInfo> rows,TextPattern doc,int depth){
        if(rows.Count>=6000||depth>55)throw new Exception("控件树超出预期，停止而不是截断匹配。");
        var c=e.Current;int i=rows.Count;string t="",value="";object p;
        if(c.ControlType==ControlType.Button||c.ControlType==ControlType.Hyperlink||c.ControlType==ControlType.DataItem){try{t=doc.RangeFromChild(e).GetText(4000);}catch{}}
        if((c.ControlType==ControlType.Hyperlink||c.ControlType==ControlType.ComboBox)&&e.TryGetCurrentPattern(ValuePattern.Pattern,out p))value=((ValuePattern)p).Current.Value;
        var patterns=e.GetSupportedPatterns().Select(a=>a.ProgrammaticName).ToArray();
        rows.Add(new NodeInfo{index=i,parent=parent,name=c.Name,id=c.AutomationId,type=c.ControlType.ProgrammaticName,text=t,value=value,enabled=c.IsEnabled,invoke=patterns.Contains("InvokePatternIdentifiers.Pattern"),patterns=patterns,element=e});
        var walker=TreeWalker.ControlViewWalker;
        for(var child=walker.GetFirstChild(e);child!=null;child=walker.GetNextSibling(child))Walk(child,i,rows,doc,depth+1);
    }
    string Clean(string s){return System.Text.RegularExpressions.Regex.Replace((s??"").Replace("\ufffc",""),@"\s+"," ").Trim();}
    NodeInfo Unique(UiSnapshot s,string name,string type){
        var items=s.nodes.Where(n=>n.type==type&&(Clean(n.text)==name||n.name==name)).ToList();
        if(items.Count!=1)throw new Exception("控件不唯一或未找到："+name+"（"+items.Count+"）。");return items[0];
    }
    InvokePattern PrepareInvoke(NodeInfo n,DateTime deadline){
        object p;if(!n.element.Current.IsEnabled||!n.element.TryGetCurrentPattern(InvokePattern.Pattern,out p))throw new Exception("控件无法通过原生接口调用。");
        if(DateTime.UtcNow>deadline)throw new Exception("请求超时，未点击。");
        return (InvokePattern)p;
    }
    void Invoke(NodeInfo n,DateTime deadline){
        PrepareInvoke(n,deadline).Invoke();
    }
    List<NodeInfo> Descendants(UiSnapshot s,NodeInfo parent){
        var ids=new HashSet<int>{parent.index};
        foreach(var n in s.nodes)if(ids.Contains(n.parent))ids.Add(n.index);
        return s.nodes.Where(n=>ids.Contains(n.index)).ToList();
    }
    void OpenAncestor(UiSnapshot s,NodeInfo n,DateTime deadline){
        for(int count=0;count<5&&!n.invoke&&n.parent>=0;count++)n=s.nodes[n.parent];
        if(!n.invoke||n.type=="ControlType.Document")throw new Exception("当前入口不支持后台调用，请在客户端打开后重试。");
        Invoke(n,deadline);
    }
    NodeInfo TeamModal(UiSnapshot s,string teamId,string teamName){
        var modal=s.nodes.SingleOrDefault(n=>n.id=="team-modal-modal-dialog");
        if(modal==null)throw new Exception("车队详情尚未打开。");
        var ns=Descendants(s,modal);
        if(!ns.Any(n=>n.name==teamName)||!ns.Any(n=>n.value!=null&&n.value.EndsWith("#modal-team-roster-"+teamId)))throw new Exception("车队名称或 Team ID 不匹配。");
        return modal;
    }
    void GuardRecovery(UiSnapshot s,Dictionary<string,object> req,bool initial){
        if(!req.ContainsKey("recovery")||!(bool)req["recovery"])return;
        if(Process.GetProcesses().Any(p=>p.ProcessName.StartsWith("iRacingSim",StringComparison.OrdinalIgnoreCase)))throw new Exception("模拟器正在运行，停止自动恢复。");
        if(s.nodes.Any(n=>n.type=="ControlType.Text"&&(n.name=="Registered"||n.name=="Registering"))||Regex.IsMatch(s.text,@"\bWithdraw\b|You may join your session\.",RegexOptions.IgnoreCase))throw new Exception("客户端存在报名或正在处理报名，停止自动恢复。");
        var start=DateTime.Parse((string)req["startUtc"],CultureInfo.InvariantCulture,DateTimeStyles.RoundtripKind).ToUniversalTime();
        if((start-DateTime.UtcNow).TotalSeconds<=180)throw new Exception("已接近目标场次截止，停止自动恢复。");
        if(initial){
            if(s.url!=(string)req["url"]||!s.nodes.Any(n=>n.name=="Global Mazda MX-5 Cup by Fanatec")||!s.nodes.Any(n=>n.name=="Global Mazda MX-5 Cup"))throw new Exception("当前不是预约的 Mazda 页面，停止自动恢复。");
            var begin=s.text.IndexOf("Next Race @");var end=s.text.IndexOf("Selected Car",Math.Max(0,begin));
            if(begin<0||end<begin)throw new Exception("无法核对自动恢复目标。");
            var card=Clean(s.text.Substring(begin,end-begin));
            var track=card.Split(new[]{"You are eligible"},StringSplitOptions.None)[0].Replace("Next Race @","").Trim();
            if(track!=(string)req["track"])throw new Exception("赛道已变化，停止自动恢复。");
        }
    }
    NodeInfo TeamAnchor(UiSnapshot snapshot,object expected){
        var spec=(Dictionary<string,object>)expected;
        int index=(int)spec["index"];
        if(index<0||index>=snapshot.nodes.Count)throw new Exception("预约控件位置已变化。");
        var n=snapshot.nodes[index];
        if(n.parent!=(int)spec["parent"]||n.type!=(string)spec["type"]||
           (n.name??"")!=(string)spec["name"]||(n.id??"")!=(string)spec["id"]||
           (n.text??"")!=(string)spec["text"]||(n.value??"")!=(string)spec["value"])
            throw new Exception("预约窗口在执行前发生变化。");
        return n;
    }
    object TeamAction(Dictionary<string,object> req,DateTime deadline){
        Action click;
        try{
            var start=DateTime.Parse((string)req["startUtc"],CultureInfo.InvariantCulture,DateTimeStyles.RoundtripKind).ToUniversalTime();
            var phase=(string)req["phase"];
            if(!new[]{"prepare","team","driver"}.Contains(phase)||DateTime.UtcNow>=start)
                throw new Exception("目标预约时间已结束。");
            var s=Read();
            if(s.url!=(string)req["url"]||!Regex.IsMatch(s.url,@"^https://members-ng\.iracing\.com/web/racing/official/series-list/\d+/go-racing$")||
                Regex.IsMatch(s.text,"disconnected|connection lost|failed to connect",RegexOptions.IgnoreCase))
                throw new Exception("iRacing 当前页面不匹配预约。");
            var anchors=((System.Collections.IEnumerable)req["anchors"]).Cast<object>().Select(x=>TeamAnchor(s,x)).ToList();
            if(anchors.Count<5||!anchors.Any(n=>Regex.IsMatch(n.name??"", @"^Team\s*\(\d+\s*[-–]\s*\d+\)$",RegexOptions.IgnoreCase))||
               !anchors.Any(n=>n.name=="Open Now")||!anchors.Any(n=>(n.name??"").StartsWith("Next Race @ ")))
                throw new Exception("尚未核对车队赛、报名窗口及下一场。");
            var next=anchors.First(n=>(n.name??"").StartsWith("Next Race @ "));
            var race=s.nodes.Skip(next.index+1).TakeWhile(n=>n.name!="Race Duration");
            var timer=race.Where(n=>n.type=="ControlType.Text").Select(n=>Clean(n.name))
                .FirstOrDefault(value=>Regex.IsMatch(value,@"^\d{1,2}:\d{2}(:\d{2})?$"));
            var now=DateTime.UtcNow;
            double remaining=(start-now).TotalSeconds;
            if(timer==null||Math.Abs(timer.Split(':').Aggregate(0,(seconds,part)=>seconds*60+int.Parse(part))-remaining)>35)
                throw new Exception("执行前倒计时已变化，未匹配目标场次。");
            var clock=Regex.Match(s.text,@"\b\d{1,2}:\d{2}:\d{2}\s[AP]M\b");DateTime clockValue;
            var zone=TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time");
            if(!clock.Success||!DateTime.TryParseExact(clock.Value,"h:mm:ss tt",CultureInfo.InvariantCulture,DateTimeStyles.None,out clockValue))
                throw new Exception("无法核对客户端时钟。");
            var clockDiff=Math.Abs((clockValue.TimeOfDay-TimeZoneInfo.ConvertTimeFromUtc(now,zone).TimeOfDay).TotalSeconds);
            if(Math.Min(clockDiff,86400-clockDiff)>35)throw new Exception("客户端时钟已停滞或时区不匹配。");
            var node=TeamAnchor(s,req["node"]);
            var label=Clean(node.text);
            if(label.Length==0)label=Clean(node.name);
            if((phase=="team"&&label!="Register Team")||(phase=="driver"&&label!="Register as Driver")||
               (phase=="prepare"&&(label=="Register Team"||label=="Register as Driver")))
                throw new Exception("当前动作与已授权步骤不一致。");
            if(!node.element.Current.IsEnabled||DateTime.UtcNow>deadline||DateTime.UtcNow>=start)
                throw new Exception("窗口不可操作或已到开赛时间。");
            object pattern;
            if(node.element.TryGetCurrentPattern(InvokePattern.Pattern,out pattern)){
                var invoke=(InvokePattern)pattern;
                click=()=>invoke.Invoke();
            }else if(phase=="prepare"&&node.element.TryGetCurrentPattern(ExpandCollapsePattern.Pattern,out pattern)){
                var expand=(ExpandCollapsePattern)pattern;
                click=()=>expand.Expand();
            }else if(phase=="prepare"&&node.element.TryGetCurrentPattern(SelectionItemPattern.Pattern,out pattern)){
                var select=(SelectionItemPattern)pattern;
                click=()=>select.Select();
            }else throw new Exception("客户端控件没有可安全使用的原生操作。");
        }catch(Exception e){return new {invoked=false,reason=e.Message};}
        // Only failures before this boundary are safe to retry.
        click();
        return new {invoked=true};
    }
    object ExecuteRequest(Dictionary<string,object> req,DateTime deadline){
        var op=(string)req["op"];
        if(op=="diagnose")return new{clientFound=IracingPath()!=null,clientRunning=Process.GetProcessesByName("iRacingUI").Length>0,simulatorRunning=Process.GetProcesses().Any(p=>p.ProcessName.StartsWith("iRacingSim",StringComparison.OrdinalIgnoreCase))};
        if(op=="shutdown"){BeginInvoke((Action)(()=>{explicitExit=true;Close();}));return new{stopped=true};}
        if(op=="launch_iracing"){
            if(LaunchIracing())Thread.Sleep(3800);
            return new{started=true};
        }
        if(op=="snapshot")return Read();
        if(op=="team_action")return TeamAction(req,deadline);
        if(op=="team_roster"||op=="team_member"||op=="team_close"){
            var teamId=(string)req["teamId"];var teamName=(string)req["teamName"];
            if(!Regex.IsMatch(teamId,@"^[1-9]\d{0,15}$")||String.IsNullOrWhiteSpace(teamName))throw new Exception("请选择有效车队。");
            var s=Read();
            if(s.url!="https://members-ng.iracing.com/web/racing/teams/my-teams")throw new Exception("请先打开我的车队。");
            if(op=="team_roster"&&!s.nodes.Any(n=>n.id=="team-modal-modal-dialog")){
                var marker=s.nodes.SingleOrDefault(n=>n.id=="favorite_teams--"+teamId);
                if(marker==null)throw new Exception("车队 ID 不在当前列表中。");
                var row=marker;while(row.parent>=0&&row.type!="ControlType.DataItem")row=s.nodes[row.parent];
                if(row.parent<0)throw new Exception("无法核对车队行。");
                row=s.nodes[row.parent];
                var cell=Descendants(s,row).SingleOrDefault(n=>n.type=="ControlType.DataItem"&&n.name==teamName);
                if(cell==null)throw new Exception("车队 ID 与名称不在同一行。");
                OpenAncestor(s,cell,deadline);Thread.Sleep(1300);s=Read();
            }
            var modal=TeamModal(s,teamId,teamName);
            if(op=="team_roster")return s;
            if(op=="team_close"){
                var close=Descendants(s,modal).Single(n=>n.type=="ControlType.Hyperlink"&&n.id.StartsWith("default-close-modal-btn-"));
                Invoke(close,deadline);Thread.Sleep(500);return Read();
            }
            var roster=s.nodes.Single(n=>n.id=="team-modal-roster");var memberName=(string)req["memberName"];
            if(s.nodes.Any(n=>n.id.StartsWith("popover-content-")))throw new Exception("请先关闭当前名片，再扫描成员。");
            var link=Descendants(s,roster).Single(n=>n.type=="ControlType.Hyperlink"&&n.name==memberName);
            Invoke(link,deadline);Thread.Sleep(1100);var result=Read();
            var cards=result.nodes.Where(n=>n.id.StartsWith("popover-content-")).ToList();
            if(cards.Count!=1)throw new Exception("未能打开唯一车手名片。");
            var card=Descendants(result,cards[0]);
            if(!card.Any(n=>n.name==memberName)||!card.Any(n=>n.name=="CustID"))throw new Exception("车手身份字段尚未加载。");
            Invoke(card.Single(n=>n.type=="ControlType.Button"&&n.name=="Close"),deadline);
            Thread.Sleep(400);return result;
        }
        if(op=="search_series"){
            var s=Read();if(s.url!="https://members-ng.iracing.com/web/racing/official/series-list")throw new Exception("请先打开官方系列列表。");
            var title=(string)req["series"];if(title.Length<3||title.Length>160)throw new Exception("系列名称无效。");
            var field=Unique(s,"Search","ControlType.Edit");object p;
            if(!field.element.TryGetCurrentPattern(ValuePattern.Pattern,out p))throw new Exception("搜索框不支持后台写入。");
            if(DateTime.UtcNow>deadline)throw new Exception("请求已过期。");
            ((ValuePattern)p).SetValue(title);Thread.Sleep(1800);return Read();
        }
        if(op=="open_series"){
            var s=Read();if(s.url!="https://members-ng.iracing.com/web/racing/official/series-list")throw new Exception("请先搜索官方系列。");
            var title=(string)req["series"];
            var items=s.nodes.Where(n=>n.type!="ControlType.Image"&&n.name==title).ToList();
            if(items.Count!=1)throw new Exception("未找到唯一的目标系列；请检查客户端筛选。");
            OpenAncestor(s,items[0],deadline);Thread.Sleep(1500);return Read();
        }
        if(op=="recover_mazda"){
            if(!req.ContainsKey("recovery")||!(bool)req["recovery"])throw new Exception("缺少自动恢复保护参数。");
            var s=Read();GuardRecovery(s,req,true);
            var links=s.nodes.Where(n=>n.type=="ControlType.Hyperlink"&&n.name=="Official"&&n.value=="https://members-ng.iracing.com/web/racing/official").ToList();
            if(links.Count!=1)throw new Exception("未找到唯一官方赛事入口。");
            Invoke(links[0],deadline);Thread.Sleep(1500);return Read();
        }
        if(op=="navigate"){
            string target=(string)req["target"];
            if(!new[]{"Official","Official Series","Go Racing","Schedule","Teams","Profile"}.Contains(target))throw new Exception("不支持的导航。");
            var s=Read();var links=s.nodes.Where(n=>n.type=="ControlType.Hyperlink"&&n.name==target&&!String.IsNullOrEmpty(n.value)).ToList();
            if(links.Count!=1)throw new Exception("导航入口不唯一："+target);
            if(target=="Teams" && links[0].value!="https://members-ng.iracing.com/web/racing/teams/my-teams")throw new Exception("未找到官方我的车队入口。");
            if(target=="Profile" && links[0].value!="https://members-ng.iracing.com/web/racing/profile")throw new Exception("未找到当前账号的官方个人资料。");
            Invoke(links[0],deadline);Thread.Sleep(1500);return Read();
        }
        if(op=="search_mazda"){
            var s=Read();if(!s.url.Contains("/official"))throw new Exception("请先进入官方赛事列表。");
            GuardRecovery(s,req,false);
            var n=Unique(s,"Search","ControlType.Edit");object p;
            if(!n.element.TryGetCurrentPattern(ValuePattern.Pattern,out p))throw new Exception("搜索框不支持后台写入。");
            if(DateTime.UtcNow>deadline)throw new Exception("请求已过期。");
            ((ValuePattern)p).SetValue("Global Mazda MX-5 Cup by Fanatec");Thread.Sleep(1800);return Read();
        }
        if(op=="open_mazda"){
            var s=Read(); var texts=s.nodes.Where(row=>row.type!="ControlType.Image"&&row.name=="Global Mazda MX-5 Cup by Fanatec").ToList();
            GuardRecovery(s,req,false);
            if(texts.Count!=1)throw new Exception("未找到唯一的 Mazda 系列，请检查赛事列表筛选。");
            var n=texts[0];
            for(int count=0;count<6&&!n.invoke&&n.parent>=0;count++)n=s.nodes[n.parent];
            if(!n.invoke||n.type=="ControlType.Document")throw new Exception("Mazda 系列没有可调用的入口。");
            Invoke(n,deadline);Thread.Sleep(1800);return Read();
        }
        if(op=="register"){
            var s=Read();
            var start=DateTime.Parse((string)req["startUtc"],CultureInfo.InvariantCulture,DateTimeStyles.RoundtripKind).ToUniversalTime();
            var remaining=(start-DateTime.UtcNow).TotalSeconds;
            if(remaining<=180||remaining>1800)throw new Exception("目标场次不在允许的报名时间范围内。");
            if(s.url!=(string)req["url"]||!s.nodes.Any(n=>n.name=="Global Mazda MX-5 Cup by Fanatec")||!s.nodes.Any(n=>n.name=="Global Mazda MX-5 Cup"))throw new Exception("执行前系列、赛季或车辆核对失败。");
            var begin=s.text.IndexOf("Next Race @");var end=s.text.IndexOf("Selected Car",Math.Max(0,begin));
            if(begin<0||end<begin)throw new Exception("执行前无法确定比赛卡片。");
            var card=Clean(s.text.Substring(begin,end-begin));
            if(s.nodes.Any(n=>n.type=="ControlType.Text"&&n.name=="Registered")&&!Regex.IsMatch(card,@"\bWithdraw\b"))throw new Exception("客户端存在其他报名，请先自行处理。");
            var times=Regex.Matches(card,@"\b\d{1,2}:\d{2}\s[AP]M\b");
            var zone=TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time");
            var label=TimeZoneInfo.ConvertTimeFromUtc(start,zone).ToString("h:mm tt",CultureInfo.InvariantCulture);
            if(times.Count==0||times[0].Value!=label)throw new Exception("执行前下一场时间已变化，未提交。");
            var clock=Regex.Match(s.text,@"\b\d{1,2}:\d{2}:\d{2}\s[AP]M\b");DateTime clockValue;
            if(!clock.Success||!DateTime.TryParseExact(clock.Value,"h:mm:ss tt",CultureInfo.InvariantCulture,DateTimeStyles.None,out clockValue))throw new Exception("无法核对客户端时钟。");
            var nowLocal=TimeZoneInfo.ConvertTimeFromUtc(DateTime.UtcNow,zone);
            var diff=Math.Abs((clockValue.TimeOfDay-nowLocal.TimeOfDay).TotalSeconds);
            if(Math.Min(diff,86400-diff)>30)throw new Exception("客户端时钟停滞或时区不匹配。");
            var countdown=Regex.Match(card,@"\b(?:(\d+):)?(\d{1,2}):(\d{2})\s+Open Now");
            if(!countdown.Success)throw new Exception("报名未开放，未提交。");
            var seconds=(countdown.Groups[1].Success?int.Parse(countdown.Groups[1].Value)*3600:0)+int.Parse(countdown.Groups[2].Value)*60+int.Parse(countdown.Groups[3].Value);
            if(Math.Abs(seconds-remaining)>30)throw new Exception("倒计时与目标开赛日期不匹配。");
            if(!card.Contains("You are eligible to race in this series!")||Regex.IsMatch(s.text,"disconnected|connection lost",RegexOptions.IgnoreCase))throw new Exception("参赛资格或连接状态未通过核对。");
            var track=card.Split(new[]{"You are eligible"},StringSplitOptions.None)[0].Replace("Next Race @","").Trim();
            if(track!=(string)req["track"])throw new Exception("赛道发生变化，未提交。");
            var button=Unique(s,"Register","ControlType.Button");
            // A click can have an external result even if the provider then times out.
            // The caller persists SUBMITTING before issuing this command.
            var action=PrepareInvoke(button,deadline);
            string at=DateTime.UtcNow.ToString("o"), state=lockState;
            action.Invoke();Thread.Sleep(1200);
            return new { invokedAt=at, invokeState=state };
        }
        throw new Exception("不支持的操作。");
    }
    [STAThread] public static void Main(){
        bool created;using(var mutex=new Mutex(true,"Local\\CodexIRacingNativeBridge",out created)){
            if(!created){MessageBox.Show("报名助手已经运行。请在 Windows 右下角托盘找到助手图标，双击后打开控制台；不要同时运行两个副本。");return;}
            Application.EnableVisualStyles();
            try{Application.Run(new NativeBridge());}catch(Exception ex){MessageBox.Show("助手初始化失败。请完整解压到可写目录（例如 D:\\iRacingAssistant），不要在 ZIP 内或只复制 exe 后运行。\n\n原因："+ex.Message,"报名助手 · 启动检查");}
        }
    }
}

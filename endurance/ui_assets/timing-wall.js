(() => {
  const root = document.getElementById("el-wall");
  const el = suffix => root.querySelector("#el-wall-" + suffix);
  const model = JSON.parse(document.getElementById("timing-wall-data").textContent);
  const labels = {"field": "全场最快", "personal": "个人最佳", "ordinary": "未刷新", "": "无排名"};
  const styles = {"field": "wall-peak", "personal": "wall-gain", "ordinary": "wall-loss", "": ""};
  let mode = "reference";
  let sector = Math.max(0, model.reference.sectors.findIndex(item => item.windows.length > 1));
  let turn = model.reference.sectors[sector].windows.length > 1 ? 1 : 0;
  let cursor = 0;
  const item = () => model[mode].sectors[sector];
  const segment = () => item().windows[turn];
  const esc = value => String(value).replace(/[&<>"']/g, char =>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[char]);
  const signed = (value, decimals = 3) => {
    const rounded = Number(value.toFixed(decimals));
    return (rounded < 0 ? "−" : rounded > 0 ? "+" : "") + Math.abs(rounded).toFixed(decimals);
  };
  const clock = time => {
    const ms = Math.round(time * 1000);
    return Math.floor(ms / 60000) + ":" + ((ms % 60000) / 1000).toFixed(3).padStart(6, "0");
  };
  const difference = pair => pair[1].value - pair[0].value;
  el("car").textContent = model.car;
  el("context").textContent = [model.track, model.build, model.simulated ? "模拟遥测" : "本机试跑"].join(" · ");
  el("change").textContent = model.change;
  root.querySelector('[data-mode="best"]').disabled = !model.best;
  el("board").style.minWidth = model.labels.length > 3 ? (187 + model.labels.length * 72) + "px" : "0";

  function plot() {
    const svg = el("chart");
    const width = Math.floor(svg.getBoundingClientRect().width);
    if (width < 165) return;
    const part = segment();
    const xmin = width < 390 ? 55 : 71;
    const xmax = width - 16;
    const x = d => xmin + d / part.length * (xmax - xmin);
    const speeds = part.traces.flatMap(t => t[0] || []);
    const low = speeds.length ? Math.floor((Math.min(...speeds) - 3) / 10) * 10 : 0;
    const high = speeds.length ? Math.ceil((Math.max(...speeds) + 3) / 10) * 10 : 100;
    const lanes = [["速度 km/h",8,69,low,high], ["刹车 %",83,38,0,100], ["油门 %",127,38,0,100]];
    svg.setAttribute("viewBox", "0 0 " + width + " 187");
    let markup = [0,.25,.5,.75,1].map((f,i) => {
      const d = f * part.length;
      if (width < 340 && (i === 1 || i === 3)) return "";
      const anchor = i === 0 ? "start" : i === 4 ? "end" : "middle";
      return '<line class="wall-grid" x1="'+x(d)+'" x2="'+x(d)+'" y1="8" y2="165"/>'+
        '<text text-anchor="'+anchor+'" x="'+x(d)+'" y="184">'+Math.round(d)+(i===4?" m":"")+'</text>';
    }).join("");
    lanes.forEach(([name, top, height, min, max], index) => {
      const y = value => top + height - (value - min) / (max - min) * height;
      markup += '<text x="7" y="'+(top+15)+'">'+name+'</text>';
      for (const v of [min,max]) {
        markup += '<line class="wall-grid" x1="'+xmin+'" x2="'+xmax+'" y1="'+y(v)+'" y2="'+y(v)+'"/>';
      }
      if (index === 0) {
        markup += '<text text-anchor="end" x="'+(xmin-5)+'" y="'+(y(min)-1)+'">'+min+'</text>'+
          '<text text-anchor="end" x="'+(xmin-5)+'" y="'+(y(max)+5)+'">'+max+'</text>';
      }
      part.traces.forEach((trace, side) => {
        const points = trace[index];
        if (!points) return;
        const poly = points.map((v,i)=>x(part.length*i/(points.length-1))+","+y(v));
        markup += '<polyline class="wall-line-'+(side?"b":"a")+'" fill="none" stroke-width="1.8" points="'+poly.join(" ")+'"/>';
      });
      if (part.traces.every(t=>!t[index])) markup += '<text x="'+(xmin+8)+'" y="'+(top+19)+'">此通道缺测</text>';
    });
    markup += '<line class="wall-cursor-line" x1="'+x(cursor)+'" x2="'+x(cursor)+'" y1="8" y2="165"/>';
    svg.innerHTML = markup;
  }

  function pointValue(samples) {
    if (!samples) return "—";
    const pos = cursor / segment().length * (samples.length - 1), index = Math.floor(pos);
    const next = Math.min(index+1,samples.length-1);
    return (samples[index]+(samples[next]-samples[index])*(pos-index)).toFixed(1);
  }
  function readout() {
    const part = segment();
    el("cursor").value = cursor;
    el("at").textContent = Math.round(cursor) + " m";
    const pair = index => part.traces.map(channels => pointValue(channels[index])).join(" → ");
    el("sample").textContent = "赛道 " + ((part.start+cursor)/1000).toFixed(3) + " km · " +
      pair(0) + " km/h · 刹车 " + pair(1) + "% · 油门 " + pair(2) + "%";
    plot();
  }
  function render(focus) {
    const current = model[mode];
    const all = current.columns.concat([current.totals]);
    el("columns").innerHTML = "<tr><th scope='col'>SETUP</th>" + model.labels.map((name,i)=>
      '<th scope="col"><button type="button" data-sector="'+i+'" aria-pressed="'+(i===sector)+'">'+esc(name)+'</button></th>'
    ).join("") + "<th scope='col'>LAP</th></tr>";
    const tableRow = (side, label, tint) => '<tr><td><span class="wall-row-key '+tint+'">'+(side?"B":"A")+'</span>'+label+'</td>'+
      all.map((pair,i)=>{
        const reading = pair[side];
        const time = clock(reading.value);
        return '<td class="'+(i===sector?"wall-split-active ":"")+styles[reading.rank]+'" aria-label="'+time+
          ' · '+labels[reading.rank]+'">'+time+'</td>';
      }).join("")+'</tr>';
    el("times").innerHTML = tableRow(0,"基准","wall-a")+tableRow(1,"调整后","wall-b")+
      '<tr class="wall-delta"><td>Δ B−A</td>'+all.map(pair=>'<td>'+signed(difference(pair))+' s</td>').join("")+'</tr>';
    el("strip").innerHTML = current.columns.map((pair,i)=>{
      const rank = pair[1].rank;
      return '<button type="button" class="wall-mark '+styles[rank]+'" data-strip="'+i+'" aria-pressed="'+(sector===i)+
        '" aria-label="'+esc(model.labels[i])+' · '+labels[rank]+'">'+esc(model.labels[i])+'</button>';
    }).join("");
    root.querySelectorAll("button[data-mode]").forEach(button=>button.setAttribute("aria-pressed",
      button.dataset.mode===(mode==="reference"?"ref":"best")));
    el("list-title").textContent = item().label + " / 遥测窗口";
    el("sector-pair").textContent = "A " + item().sources[0] + " / B " + item().sources[1];
    el("turns").innerHTML = item().windows.map((part,i)=>'<button class="wall-turn" type="button" data-turn="'+i+
      '" aria-pressed="'+(i===turn)+'"><span>'+esc(part.name)+'</span><span class="wall-num">'+
      signed(part.times[1]-part.times[0])+' s</span></button>').join("");
    el("basis").textContent = item().windows.length > 1 ? "列出本段内已核对的弯道窗口。" : "本段暂无已核对的弯道窗口。";
    const part = segment();
    el("detail-title").textContent = part.name;
    el("detail-note").textContent = (part.start/1000).toFixed(3) + "–" + ((part.start+part.length)/1000).toFixed(3) + " km" +
      (part.crosses_timing_line ? " · 跨计时线，沿用本段来源圈" : "");
    el("corner-delta").textContent = signed(part.times[1]-part.times[0])+" s";
    el("metrics").hidden = !part.metrics.length;
    el("metrics").innerHTML = part.metrics.map(({label, unit, pair})=>{
      const precision = unit==="g" ? 2 : 1;
      const values = pair.map(({value,rank}) => value===null ? "—" :
        '<strong class="'+styles[rank]+'" aria-label="'+value.toFixed(precision)+" "+unit+" · "+
        (unit==="km/h" && rank==="personal" ? "个人最快速度" : labels[rank])+'">'+value.toFixed(precision)+'</strong>');
      const delta = pair.some(r=>r.value===null) ? "缺测" : signed(difference(pair), precision)+" "+unit;
      return '<div><small>'+esc(label)+'</small><b class="wall-num">'+values.join(" → ")+'</b><span>'+unit+' · '+delta+'</span></div>';
    }).join("");
    el("cursor").max = part.length;
    el("cursor").step = Math.max(1, Math.floor(part.length/500));
    cursor = part.points[1] ?? Math.min(cursor, part.length);
    readout();
    if (focus) root.querySelector(focus)?.focus();
  }
  root.addEventListener("click", event => {
    const b = event.target.closest("button");
    if (!b || !root.contains(b)) return;
    const {mode: nextMode, sector: nextSector, strip, turn: nextTurn} = b.dataset;
    if (nextMode) { mode = nextMode==="ref" ? "reference" : "best"; render(); }
    else if (nextSector !== undefined || strip !== undefined) {
      sector = Number(nextSector ?? strip);
      turn = item().windows.length > 1 ? 1 : 0;
      render(nextSector === undefined ? '[data-strip="'+sector+'"]' : '[data-sector="'+sector+'"]');
    } else if (nextTurn !== undefined) {
      turn = Number(nextTurn); render('[data-turn="'+turn+'"]');
    }
  });
  el("cursor").addEventListener("input", event => { cursor = Number(event.target.value); readout(); });
  el("chart").addEventListener("pointerdown", event => {
    const bounds = el("chart").getBoundingClientRect();
    const left = bounds.width<390 ? 55 : 71;
    const fraction = (event.clientX - bounds.left - left)/(bounds.width-16-left);
    cursor = Math.max(0, Math.min(1, fraction)) * segment().length;
    readout();
  });
  new ResizeObserver(plot).observe(el("chart"));
  render();
})();

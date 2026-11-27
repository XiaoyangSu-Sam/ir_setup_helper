# iRacing Tools 项目指南

## 开发入口

- 此仓库包含个人耐力赛调教助手和 Windows 合装包。调教助手使用 Python、Streamlit、Polars、Parquet 和 DuckDB。界面以中文说明，游戏参数保留原名。
- 调教助手入口为 `launch.py` 和 `app.py`，业务代码在 `endurance/`，车型和参数依据在 `config/`。本地可运行 `.venv\Scripts\python.exe launch.py --no-browser`。源码版默认端口 19391，安装版默认端口 19392。
- 设置建议应区分实际遥测、主观感受和理论估计。参数数值需有相应版本的证据，Passed Tech 由游戏确认。保留失败圈和缺字段记录。

## 报名助手

- 报名助手独立运行，入口是合装目录中的 `registration/NativeBridge.exe`，本机控制台在 `127.0.0.1:19390`。调教助手不操作它正在使用的 iRacing 页面。
- `packaging/registration-release.json` 固定干净的基础运行包和 SHA-256。`registration/` 保存本仓库维护的改动。`scripts/stage_registration.py` 先验基础包，再只覆盖 `PROJECT_OVERRIDES` 指定的文件。更新基础包时，逐项核对覆盖文件与上游的接口及行为。
- 耐力赛目录以官方赛季赛历和特殊赛事为主。赛历按多伦多当地开赛日期分组。使用明确的官方报名窗口和赛程天气，缺失时标为待确认。客户端的 Team Registration 排序可辅助浏览车队系列。核对场次、车辆名单和是否开放时，以客户端实际页面为准。公开赛历的简称与客户端标题不一致时，在对应赛事的日期和来源下明确记录映射。
- 参赛条件分别记录车辆授权、赛道授权和驾照。多组别赛事核对当前选中的车型。来源不足时保留待确认。参赛条件、场次是否开放、整队报名和车手加入分别读取各自的凭据。
- 实机测试使用只读检查。真实报名、购买及启用预约由用户明确授权。安装升级保留调教记录和报名助手的 `data/`。遥测、名单、访问密钥和本机日志不要进入 Git 或安装包。

## 测试与发布

- 运行 `python -X utf8 -m pytest -q` 和 `node --test tests/registration/eligibility.test.mjs`。Windows 合装构建会用包内 Node 跑资格与赛历测试。单独运行 `calendar.test.mjs` 时，将 `IR_REGISTRATION_TEST_RUNTIME` 指向已暂存的报名目录。
- `scripts/build_windows.ps1` 生成单独调教版。传入基础运行包 `-RegistrationPackage` 生成合装版。用 `scripts/smoke_windows.ps1` 验证两个安装器，合装版加 `-WithRegistration`。
- 版本取自 `pyproject.toml`，发布标签为 `v<版本>`。标签触发 GitHub Actions 构建和测试两个 Windows 安装包，通过后在同一个 Release 发布附 SHA-256 的资产。

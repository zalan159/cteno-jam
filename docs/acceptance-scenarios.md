# Cteno Jam acceptance scenarios · 验收场景（jam.cteno.cn）

Every scenario has an automated test that turns red when the behaviour breaks. Public-site scenarios run
**through a front proxy with the production rules** (relay suite, `scripts/e2e_relay.sh`, rules file
[`deploy/relay/jam.rules.caddy`](../deploy/relay/jam.rules.caddy)); phone scenarios run at 390×844
(phone suite, `scripts/e2e.sh`). `scripts/e2e_all.sh` runs both; `scripts/unit.sh` runs pytest + node tests.

每条场景都要有一条会红的自动化测试。公网相关场景必须**经过与生产同规则的中转层**跑（e2e relay 套件），手机场景用 390×844。

Source: the product owner's list (2026-11-07). Changes against it are marked **修正** with the reason.

## A. 打开就有歌

- **A1** 未登录、不搜索，手机打开首页：第一屏不滚动就能看到 ≥5 首可点的歌；没有标语、星星等装饰，也没有常驻上传卡。
- **A2** 首页有「热门 / 中文 / 我的曲库」三栏，默认「热门」；切换栏目时第一首歌的位置不跳。
- **A3** 每行歌都显示热度、许可证，有试听和「用这首」。
  - **修正**：试听和「用这首」只适用于 Jamendo 的行；本站曲库的行显示热度、来源、许可证，点击（或「打开」按钮）直接进谱子页，没有单独的试听按钮。原因：本站歌已经处理好，打开就能播，没有可试听的预览流。
- **A4** Jamendo 出错、返回空结果或没配置时：仍显示本站曲库，不出现空白页，不报错弹窗。
- **A5** 「中文」栏至少 10 首（Jamendo lang=zh，不够就按标签补）；实际数量写进报告。
  - **修正**：自动化测试用假 Jamendo（`scripts/fake_jamendo.py`：6 首 lang=zh + 6 首只有 chinese 标签），断言补齐后 12 首、≥10；线上真实数量要在部署后公网冒烟里数（2026-11-07 公网实测 20 首，见交付报告）。原因：测试不能依赖真实 Jamendo 的曲目变化。

## B. 用一首歌

- **B1** 点 Jamendo 的「用这首」：导入、排队、处理，能看到进度；完成后进入谱子页。
  - **修正（行为补齐）**：原来点完只弹「已添加，正在排队」，并且热门栏只显示处理好的歌，看不到进度，处理完也不会进谱子页。现在点完切到「我的曲库」显示排队和处理进度，处理完自动打开谱子页（中途切栏目、搜索或打开上传就不再自动跳）。
- **B2** 点本站曲库里已处理好的歌：直接进谱子页并开始播放，播放计数 +1（同一会话 30 秒内只算一次）。
  - **修正**：进谱子页后由用户点播放才开始放（浏览器不允许无手势自动出声，iOS Safari 尤其如此）；计数在真正开始播放时 +1。
- **B3** 同一首 Jamendo 歌已导入过：列表里只出现一次，再点不会重复导入。

## C. 上传

- **C1** 点「上传」弹出上传层，支持选文件和网页录音；传完自动关闭，跳到「我的曲库」，新歌排在可见位置。
- **C2** 上传 mp3 / m4a / wav / flac / amr 都能处理成功。
- **C3** 上传 QQ 音乐等加密文件、坏文件、超长（>600 秒）、超大（>50MB）：上传时就拒绝，并用中文说清原因；不进队列，不留失败记录。
  - **修正（行为补齐）**：原来坏文件和超长文件要进队列、处理到「解码」才失败，留下一条失败记录；超大文件的提示是英文 `file larger than 50 MB`。现在服务器收完文件先用 ffprobe 检查，读不出、短于 5 秒、长于上限的当场拒绝并删掉；超大的提示改成中文；前端选文件时就按上限拦下超大文件；中转层的 52MB 请求体上限返回 413。
- **C4** 公网同一 IP 1 小时超过 5 次、队列满、磁盘超 80%：拒绝并说明原因。
  - **修正**：自动化测试把阈值调小（每小时 1–2 次、队列 2 首、磁盘 1%）验证同一套逻辑，生产值（5 次 / 20 首 / 80%）写在 docker-compose.yml，不在测试里改生产配置。被拒绝的上传（坏文件、加密、超长）不计入每小时次数。

## D. 管理自己的歌（公网）

- **D1** 在本浏览器上传的歌：显示删除 / 改名 / 重试 / 编辑，经中转层操作成功。
- **D2** 别人上传的歌、内置演示歌：不显示这些按钮；直接调接口返回 403，并带中文原因。
- **D3** 换浏览器或清了缓存：自己的歌也变成「别人的歌」（D2 的行为），不会报错。
- **D4** 管理员命令能在服务器上删掉任意一首歌（包括旧的失败记录）。
  - 补充：令牌机制之前上传的旧歌没有令牌，公网上谁都删不了（预期行为），只能用管理员命令删。命令见 [deploy.md](deploy.md#managing-songs--管理歌曲-2026-11-07)。

## E. 演奏与同步

- **E1** 谱子页：和弦标在正在唱的字上方，播放时跟随滚动。
- **E2** 变调、变速、单独静音某一轨，在手机 Safari 和微信内置浏览器里都生效。
- **E3** 分享房间：另一台手机扫码加入后同步播放进度；遥控模式能控制大屏。
  - **修正**：自动化测试用打开分享链接代替扫码（二维码内容就是这个链接）。

## F. 部署与回归

- **F1** 每次部署前备份 src、data 和镜像 tag；部署后在公网跑 A1、B2、D1、D2 冒烟。
- **F2** 任何改动都必须跑 relay 套件和手机尺寸套件。

## Coverage · 覆盖表

Test names are `file › test`. "phone" = `scripts/e2e.sh` (webkit-iphone, chromium-iphone, chromium-desktop),
"relay" = `scripts/e2e_relay.sh` (webkit-iphone, chromium-iphone; desktop skipped).

| 场景 | 测试 | 套件 |
|---|---|---|
| A1 | `e2e/tests/home.spec.js › home first screen: tabs + ≥5 playable songs, no stars, no upload card; 中文 tab; upload sheet`；公网规则下再测一次：`e2e/tests/relay.spec.js › public smoke through the relay: A1 first screen, B2 …` | phone, relay |
| A2 | `home.spec.js › home first screen …`（断言三栏名称、默认热门、`zh.firstSongTop == hot.firstSongTop`） | phone |
| A3 | `home.spec.js › home first screen …`（每行有热度+许可证；每个 Jamendo 行有 `.jmPlay` 和 `.jmUse`）；`e2e/tests/sources.spec.js › search mixes the library with Jamendo …`（试听真的出声、经服务器代理） | phone |
| A4 | `home.spec.js › Jamendo down: …`；`home.spec.js › Jamendo answers with empty lists: …`；`home.spec.js › no Jamendo client id: …`；`sources.spec.js › no Jamendo client id: search only looks in the library …`；服务端：`server/tests/test_audio_sources.py › test_chart_failure_is_502_and_not_cached`、`test_chart_rides_out_a_run_of_bogus_empty_answers_and_keeps_the_last_good_list` | phone, pytest |
| A5 | `home.spec.js › home first screen …`（`home-zh-count` = 12，≥10）；`test_audio_sources.py › test_zh_chart_tops_up_from_tags_and_dedupes`、`test_zh_chart_falls_through_to_chinese_asian` | phone, pytest |
| B1 | `home.spec.js › use a Jamendo song from the home list: import, progress, then the chart opens`（webkit-iphone） | phone |
| B2 | `relay.spec.js › public smoke … B2 open a library song and play (+1)`；`sources.spec.js › search mixes … plays are counted`；`server/tests/test_popularity.py › test_play_is_counted_once_per_session_within_30s` | relay, phone, pytest |
| B3 | `sources.spec.js › search mixes …`（导入后只出现一次，再导入返回同一首）；`test_audio_sources.py › test_reimporting_a_jamendo_track_returns_the_library_copy`；`server/tests/test_owner.py › test_jamendo_import_returns_a_token`（重复导入不再发令牌） | phone, pytest |
| C1 | `home.spec.js › home first screen … upload sheet`（上传层自动关闭、切到我的曲库、新歌在视口内）；`sources.spec.js › entry points: record and files/WeChat tip …`；`sources.spec.js › record in the browser → use it → …`（Chromium；WebKit 没有采集设备） | phone |
| C2 | `server/tests/test_formats_pipeline.py › test_format_is_processed_end_to_end[.mp3/.m4a/.wav/.flac/.amr]`（真 Demucs 流水线）；`server/tests/test_upload_checks.py › test_every_phone_format_is_accepted_and_measured[…]` | pytest |
| C3 | 加密：`test_api.py › test_encrypted_upload_refused_with_friendly_message`、`jam.spec.js › encrypted music-app files are refused …`；坏文件：`test_upload_checks.py › test_broken_file_is_refused_at_upload[…]`、`jam.spec.js › broken file refused at upload; …`；超长：`test_upload_checks.py › test_longer_than_600_s_is_refused`、`test_too_short_is_refused`；超大：`test_upload_checks.py › test_bigger_than_the_limit_is_refused_in_chinese`、`relay.spec.js › C3: a file over the limit is refused before uploading; the relay answers 413 …` | pytest, phone, relay |
| C4 | `test_api.py › test_per_ip_hourly_limit_uses_forwarded_for`、`test_queue_limit_rejects_when_full`、`test_disk_guard`；`test_upload_checks.py › test_refused_uploads_do_not_count_against_the_hourly_limit` | pytest |
| D1 | `relay.spec.js › D1: my own upload — rename, edit, delete through the relay`；`relay.spec.js › D1: my own failed upload can be retried through the relay`；`relay.spec.js › relay: writes without a token are 403 at the relay, wrong token 403 at the server, own token works`；`test_owner.py › test_owner_can_rename_edit_retry_and_delete` | relay, pytest |
| D2 | `relay.spec.js › D2: someone else's song and the demo song show no management buttons; direct calls are 403 in Chinese`；`test_owner.py › test_without_the_right_token_every_write_is_403_in_chinese[…]`（6 个接口 × 4 种错令牌）、`test_a_token_cannot_manage_another_song`、`test_demo_song_cannot_be_deleted_even_with_a_token_guess`、`test_old_songs_without_a_token_cannot_be_managed_over_http` | relay, pytest |
| D3 | `relay.spec.js › D3: another browser (or cleared site data) treats my song as someone else's, without errors` | relay |
| D4 | `test_owner.py › test_admin_cli_lists_and_deletes_any_song`、`test_admin_cli_runs_as_a_module` | pytest |
| E1 | `jam.spec.js › upload → process → play → …`（步骤 `chords-over-words`：每个和弦在它的字正上方，跳到第 10 行后该行滚进视野） | phone |
| E2 | 部分：`jam.spec.js › upload → process → play → …`（WebKit/Chromium 手机尺寸：变调 +2、变速、单轨 solo/静音，测了实际电平）；`e2e/ios/run_sim_gui.sh`（iOS 模拟器里的真 Mobile Safari，录系统声音）。**微信内置浏览器未覆盖**，见下 | phone, iOS sim (manual run) |
| E3 | `jam.spec.js › upload → process → play → share → big screen → remote`（第二台设备打开分享链接后跟随、大屏、遥控暂停和变调） | phone |
| F1 | **未自动化**，见下 | — |
| F2 | `scripts/e2e_all.sh` 两套都跑，任一失败退出码非 0 | — |

### Not covered (yet) · 还没覆盖的

- **E2 微信内置浏览器**：需要真机上的微信（X5/XWEB 内核），Playwright 和 iOS 模拟器里都没有微信。iOS 上微信内置浏览器用的是系统 WKWebView，和 Safari 同一个引擎，模拟器 Safari 的结果可以参考，但不能代替。要自动化得接一台真机（iOS 用 WebDriverAgent，Android 用 adb + 微信调试模式）。
- **E2 iOS Safari** 的 `run_sim_gui.sh` 需要 Mac 的图形会话和模拟器，不在 `e2e_all.sh` 里自动跑；这次交付没有重跑。
- **F1 部署前备份 + 部署后公网冒烟**：是部署流程，不是代码行为。部署后的公网冒烟可以直接用 relay 套件对生产跑（`JAM_RELAY=1 JAM_URL=https://jam.cteno.cn npx playwright test tests/relay.spec.js`），但它会在生产上传和删除测试歌，要等部署人确认后再跑；备份步骤写在 [deploy.md](deploy.md)。

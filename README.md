# 墨水屏日历

适用于 **ESP32-L + DESPI-C73 + GDEP073E01** 的离线电子日历。屏幕为 7.3 英寸、800 × 480、六色。实物主控是经典 ESP32；本项目不使用 ESP32E6-E01 / ESP32-S3 的配置。

日历页面在 Mac 上提前生成，压缩后写入开发板 Flash。设备由 DS3231 时钟模块提供日期，每天零点后醒来，刷新当天的页面，然后深度睡眠到第二天。运行时不需要网络或后端服务。

还没有 DS3231 时，固件会自动改用**内部时钟模式**：芯片保持唤醒，用晶振计时，必须一直插着 USB 电源（见下文）。

> 当前状态：固件编译通过，存储读取和时钟驱动已在 Mac 上用模拟环境测试；**尚未在实物上运行**。屏幕方向、实际刷新时间、睡眠电流和 DS3231 接线都需要上板确认。

## 需要的硬件

| 部件 | 说明 |
| --- | --- |
| ESP32-L + DESPI-C73 + GDEP073E01 | 已有。接线见 `docs/hardware.md` |
| DS3231 时钟模块 | I²C 接口，需要另外购买。带纽扣电池座，主电源断开后继续计时。没有它时只能长期插 USB 电源 |
| 电池 | 尚未确定。ESP32-L 的电池接口和充电电路需要对照实物确认 |

DS3231 默认接在 GPIO21（SDA）和 GPIO22（SCL），这是 LOLIN32 的默认 I²C 引脚。**这两个引脚在 ESP32-L 排针上是否引出、是否空闲，还没有确认**；如果不能用，修改 `epaper_calendar.ino` 中的 `kRtcSdaPin` / `kRtcSclPin`。

## 每年一次：生成并写入页面

```sh
python3 -m pip install --user -r scripts/requirements.txt   # Pillow、pyserial（见下方说明）

python3 scripts/generate_pages.py --start 2026-11-09         # 365 张 PNG + fallback.png → .build/pages/
python3 scripts/pack_calendar.py .build/pages                # 压缩打包 → .build/calendar-data.bin
scripts/compile.sh                                           # 编译固件（不上传）
```

Homebrew 安装的 Python 默认禁止直接用 pip 装包（PEP 668），上面的命令会报 `externally-managed-environment`。解决办法二选一：
- 在命令末尾加上 `--break-system-packages`：包只会装进用户目录 `~/Library/Python/`，不会改动 Homebrew 的 Python；
- 或者先建一个虚拟环境（`python3 -m venv .venv && source .venv/bin/activate`），然后去掉 `--user` 再安装。

连接开发板后：

```sh
# 1. 上传固件：Arduino IDE 点 →，或
"/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli" \
  upload -p /dev/cu.usbserial-XXXX --fqbn esp32:esp32:lolin32 \
  --board-options UploadSpeed=460800 \
  --input-dir .build/epaper_calendar firmware/epaper_calendar

# 2. 写入页面数据（只写 calendar 分区，不影响固件）
scripts/flash_data.sh /dev/cu.usbserial-XXXX

# 3. 把北京时间写入时钟（DS3231 或内部时钟）
python3 scripts/set_rtc.py /dev/cu.usbserial-XXXX
```

默认的 921600 波特率经过 USB 扩展坞时，板子上的 CH340 会断开连接，所以这里降到 460800。`flash_data.sh` 也用 460800。

`set_rtc.py` 固定发送北京时间（`Asia/Shanghai`），不受 Mac 上 `TZ` 环境变量的影响；需要其他时区时用 `--tz`。

固件和页面数据分开烧录：更新代码不用重写页面，换页面也不用重新编译。上传固件**不会**擦除页面数据，除非在 IDE 中启用了 “Erase All Flash”。

### 页面与容量

- `generate_pages.py` 默认使用**黄历风**（`--style almanac`）：大号衬线日期；竖排红色农历印章；节气和节日用黄色标签；底部显示一年中的第几天，以及距离下一个重要节日还有几天。周末和重要节日的日期显示为红色。另外两种风格是月历风 `--style grid`（左侧当天日期，右侧带农历的整月月历）和海报风 `--style poster`（整版色块，底部显示本周七天）。
- 农历来自 macOS 自带的中国历法（`calendar_info.py` 通过 JavaScript for Automation 调用），干支、生肖、闰月都能正确处理。节气根据太阳视黄经计算，误差约 15 分钟，如果某个节气恰好落在零点前后几分钟，日期可能差一天。节日包括春节、除夕、元宵、端午、七夕、中秋、重阳等传统节日，以及元旦、劳动节、国庆、母亲节等公历节日。**国务院每年公布的放假和调休安排没有包含**。
- 页面用到的字体都是 macOS 自带的：宋体、冬青黑体、Bodoni 72、DIN Condensed、Futura。文字不做抗锯齿，渲染出来的每个像素都正好是六色之一。
- 生成页面后，用浏览器打开 `preview/calendar.html` 就能预览：页面上有和外壳一样的 7 个按键（也可以用键盘操作），能把“今天”设成任意日期，旁边显示和固件一样的串口日志。改了页面设计后，重新运行 `generate_pages.py`，再刷新网页即可。
- 每个月还会生成一张整月月历 `YYYY-MM.png`，给月历键用。13 张约 76 KB。固件按 `generate_pages.py` 里 `MONTH_GRID_*` 的格子位置给今天那一格换色。改月历版式时，要同步修改固件里的 `kMonthGrid*`，测试会检查两边是否一致。
- 也可以用其他工具设计页面。只要文件名是 `YYYY-MM-DD.png`（月历是 `YYYY-MM.png`），尺寸是 800 × 480，放进同一个目录即可。`fallback.png` 用于时钟未设置或缺少当天页面的情况。
- 黄历风每张页面压缩后约 4 KB，365 天约 1.47 MB，数据分区容量是 2.75 MB（2,818,048 字节）。照片类页面每张约 85 KB，放不下一整年。`pack_calendar.py` 会打印用量，超出容量时直接报错。
- `pack_calendar.py` 支持 `--fit`、`--rotate`、`--dither`，含义和 `convert_image.py` 相同。

## 固件行为

开机时检测 DS3231，根据结果进入两种模式之一：

| | DS3231 模式 | 内部时钟模式（没有 DS3231） |
| --- | --- | --- |
| 计时 | DS3231，断电后仍然继续 | ESP32 晶振（`esp_timer`），任何复位或断电都会丢失时间 |
| 刷新后 | 深度睡眠到第二天 | 保持唤醒，跨过零点时刷新 |
| 供电 | 可以用电池 | **必须一直插着 USB 电源**，芯片持续耗电约几十毫安 |
| 校时 | 复位后 5 秒窗口内 | 任何时候都可以（但测试用的 ESP32-L 打开串口就会复位，见下文） |

内部时钟模式只是 DS3231 到货前的过渡方案。晶振计时通常每天只差几秒，实际误差需要测量：每次运行 `set_rtc.py`，固件都会打印“Clock was +N s off after X h (+Y s/day)”，也就是距上次校时偏了多少秒、按天折算的误差。建议先每周校一次。注意，以下操作都会复位芯片，内部时间随之丢失，屏幕会显示 fallback 页面，需要重新校时：
- 上传固件；
- 按复位键；
- **打开串口**：测试用的 ESP32-L（CH340）在 Mac 上只要打开串口就会复位，`set_rtc.py` 和 Arduino 串口监视器都一样。`set_rtc.py` 打开串口后会等板子重启，在 5 秒窗口内发送时间，校时成功后保持串口打开，一直读到刷屏结束。校时之后不要再打开串口，否则时间会丢失；
- Mac 休眠或扩展坞断电导致 USB 断电。

### 按键

7 个按键从左到右依次是：激活、上一月、上一天、今天、下一天、下一月、月历。接线见 `docs/hardware.md`。

- **翻页：**
  - 翻页键连按会累计，停手 1.5 秒后才刷屏，避免每按一次闪一次；
  - 翻到没有页面的日期时停在原处；
  - 翻看时 2 分钟不操作，自动回到今天。
- **今天：** 回到今天并强制重刷。
- **月历：** 在当天页和这个月的整月月历之间切换。今天那一格显示成红底白字的圆角块：月历底图是提前画好的，固件在显示时给这一格换色。月历视图里按上一月、下一月翻的是月历页；按上一天、下一天或“今天”，回到单日页。
- **时钟没设置时：** 只有“今天”有用。
- **刷屏期间：** 屏幕刷新要二三十秒，这段时间按键无效。

DS3231 模式下只有激活键能把芯片从深度睡眠中唤醒。醒来后 30 秒内其他键可用，没有操作就继续睡。如果还在翻看其他日期，2 分钟后会自己醒来切回今天。

DS3231 模式每次醒来：读取 DS3231 时间 → 如果日期变了，从 Flash 找到当天页面，先完整解压一遍校验 CRC 和长度，校验通过才开始刷屏 → 关闭屏幕驱动 → 深度睡眠。

- **刷新时间**：每天 00:00:30 之后。ESP32 睡眠计时用的是内部 RC 振荡器，误差可能有百分之几，所以长时间睡眠只睡剩余时间的 90%，醒来后用 DS3231 重新计算剩余时间，最后 10 分钟以内一次睡完。预计实际刷新时间会在零点后一分钟以内，需要实物验证。
- **每个日期只刷新一次**：已显示的日期记录在 RTC 内存里，深度睡眠后保留，断电后清空。重新上电会刷新一次。
- **时钟问题**：DS3231 没有响应，或时间丢失（首次上电、纽扣电池没电）时，显示 `fallback.png`，之后每 6 小时检查一次。
- **校时**：上电或按复位键后，固件等待 5 秒，接收 `SET YYYY-MM-DD HH:MM:SS` 命令；内部时钟模式下随时都能接收。`set_rtc.py` 打开串口后先直接发送一次；设备没有回应时，再复位板子并在这个窗口内发送。从深度睡眠醒来时不等待。
- **卡死保护**：厂商的 BUSY 等待没有超时。固件开启了 120 秒任务看门狗：如果刷新卡住，芯片会复位，复位后跳过刷屏，直接睡到第二天。这只能限制电池被持续耗光，**不能修复卡住的原因，也不是过热保护**。看门狗复位时屏幕驱动可能还没关闭。欠压复位后同样跳过刷屏。

## 在 Arduino IDE 中开发

1. 打开 `firmware/epaper_calendar/epaper_calendar.ino`。文件夹名与主 `.ino` 文件名需要一致，同目录的 `.h`、`.cpp`、`partitions.csv` 要一起保留。
2. 开发板选择 **WEMOS LOLIN32**（esp32 by Espressif Systems，支持包 **3.3.11**）。同目录下的 `partitions.csv` 会自动替换默认分区表，**不需要**在菜单里选择 Partition Scheme。
3. 用能传输数据的 USB 线接入 Mac，选择新出现的 `/dev/cu.usbserial-…` 端口。
4. 串口监视器波特率设为 **115200**。每个阶段都会输出以 `[calendar]` 开头的日志。

2026-11-09 使用 Arduino CLI 1.5.1、ESP32 core 3.3.11 编译：程序 333,540 / 1,310,720 字节（25%），全局变量 23,764 / 327,680 字节（7%）。

## 项目结构

| 位置 | 用途 |
| --- | --- |
| `firmware/epaper_calendar/epaper_calendar.ino` | 入口：读时钟、选页面、刷新、深度睡眠 |
| `firmware/epaper_calendar/calendar_store.*` | 读取 Flash 中的页面数据，用 ESP32 ROM 中的 miniz 流式解压 |
| `firmware/epaper_calendar/rtc_ds3231.*` | DS3231 读写和日期计算 |
| `firmware/epaper_calendar/partitions.csv` | 4 MB Flash 分区：程序 1.25 MB，页面数据 2.75 MB |
| `firmware/epaper_calendar/Display_EPD_W21*` | 原样保留的厂商屏幕驱动 |
| `firmware/epaper_calendar/image.h` | 厂商示例图，原样保留，**不再编译进固件** |
| `scripts/generate_pages.py` | 生成每日页面 PNG |
| `scripts/pack_calendar.py` | 页面 → 压缩数据文件 |
| `scripts/convert_image.py` | 单张图片 ↔ 六色 C 数组 / 预览图 |
| `scripts/compile.sh` | 只编译，不上传 |
| `scripts/flash_data.sh` | 把页面数据写入已连接开发板的 calendar 分区 |
| `scripts/set_rtc.py` | 通过 USB 串口校时 |
| `docs/hardware.md` | GPIO、DS3231 接线、分区与数据格式 |
| `preview/calendar.html` | 网页版日历模拟器：显示 `.build/pages/` 里的页面，按键逻辑和固件一致，浏览器直接打开 |
| `enclosure/calendar_frame.scad` | 3D 打印相框模型（OpenSCAD） |
| `enclosure/build_viewer.py` | 导出 STL，生成 three.js 3D 预览页面 |
| `enclosure/viewer.html` | 3D 预览页面，浏览器直接打开（由上面的脚本生成） |
| `docs/enclosure.md` | 外壳尺寸记录、打印与组装说明 |
| `vendor/ESP32-GDEP073E01.zip` | 用户提供的原始厂商压缩包 |

## 单张图片转换

```sh
python3 scripts/convert_image.py encode page.png -o page.h --preview page-preview.png
python3 scripts/convert_image.py encode portrait.png -o page.h --rotate 90          # 480 × 800 竖版
python3 scripts/convert_image.py encode photo.jpg -o page.h --fit cover --dither     # 照片
python3 scripts/convert_image.py preview firmware/epaper_calendar/image.h -o preview.png
```

- 输出格式与厂商 `image.h` 相同（`gImage_1[384000]`，每像素 1 字节）。现在的固件不使用这种数组，这个工具主要用来预览页面在六色屏上的效果。
- 默认要求输入恰好是 800 × 480；需要缩放时用 `--fit contain`（留边）或 `--fit cover`（裁切）。
- 最近色按 CIELAB 色差计算，避免抗锯齿文字边缘的灰色被误判为黄色。
- `--rotate` 表示设计稿顺时针旋转的角度。屏幕实际安装方向尚未确认。
- 预览图使用纯 RGB 颜色，实物会更暗、更偏灰。

## 测试

```sh
python3 -m unittest discover -s scripts
```

测试覆盖以下内容：
- 厂商示例的双向比对；
- 色彩量化；
- 打包格式的往返转换和损坏检测；
- 生成页面的大小上限；
- 六周月份和闰日。

固件中的 C++ 存储读取、DS3231 驱动和日期换算另外在 Mac 上用模拟的 I²C 和 zlib 测试过。这些测试脚本没有放进仓库，测不到 ESP32 ROM 里的解压器本身。

## 上板前要确认的事

1. ~~内部时钟模式~~：已验证。不接 DS3231 时进入内部时钟模式，显示 `fallback.png`；运行 `set_rtc.py` 后切换到当天的页面。
2. ~~ESP32-L 的 Flash 大小~~：已经用 `esptool flash-id` 确认是 4 MB（芯片 ESP32-D0WD v1.1，USB 串口芯片 CH340）。
3. GPIO21/22 是否可用，以及 DS3231 接上后 `set_rtc.py` 能否校时成功。
4. ~~屏幕方向和实际颜色~~：已确认，显示正常，不需要 `--rotate`。
5. 深度睡眠电流：需要在电池供电下实测，用来估算续航。电流主要取决于开发板上的稳压芯片、USB 串口芯片和指示灯，代码只能控制 ESP32 本身。
6. 屏幕深度睡眠：厂商代码把深睡眠命令（0x07）注释掉了，目前只发送断电命令（0x02）。是否启用 0x07 来进一步省电，需要对照屏幕资料并在实物上测量后再决定。

调试时不要反复快速复位，以免频繁刷新屏幕。插拔排线、改接线之前先断电。若再次出现异常发热，立即断电检查。

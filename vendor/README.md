# 厂商源码来源

原始文件由用户提供：`ESP32-GDEP073E01.zip`。

SHA-256：`3c0136e7bfc45925d134f3dd550813faac4dc7fd2023daa382db88649099a430`。

压缩包中的工程位于 `ESP32/GDEP073E01/`。这里保留原始压缩包，便于随时比对厂商版本。

以下文件复制到当前工程后保持字节一致：

- `Display_EPD_W21.cpp`
- `Display_EPD_W21.h`
- `Display_EPD_W21_spi.cpp`
- `Display_EPD_W21_spi.h`
- `image.h`

项目自己的入口 `epaper_calendar.ino` 替代原厂 `GDEP073E01.ino`，主要调整：

- 添加 115200 波特率的阶段日志。
- 明确 GPIO 映射，先启动 SPI 总线，再开启事务。
- 使用普通全刷 `EPD_init()`，而不是原厂入口里的 `EPD_init_fast()`。
- 页面数据从 Flash 的 calendar 分区读取，按厂商 `PIC_display()` 的时序（0x10 → 数据 → 0x12 → 等待 BUSY）发送；每个日期只刷新一次，然后调用原厂 `EPD_sleep()`。
- 去掉入口里的连续纯色演示和最终清屏；刷新后主控进入深度睡眠。
- `image.h` 原样保留在目录中，但入口不再包含它，所以不会编译进固件。
- 保留原厂的底层驱动参数、图像编码和关闭屏幕驱动流程；驱动文件没有修改。

原压缩包未附独立许可证文件；本项目不为厂商代码另行声明许可证。

#include <Arduino.h>
#include <SPI.h>

#include "Display_EPD_W21.h"
#include "Display_EPD_W21_spi.h"
#include "image.h"

// ESP32-L + DESPI-C73 + GDEP073E01. Select WEMOS LOLIN32 in Arduino IDE.
#if !defined(CONFIG_IDF_TARGET_ESP32)
#error "This sketch targets the classic ESP32. Select WEMOS LOLIN32, not ESP32-S3."
#endif

// Keep the vendor driver's A14-A17 aliases tied to the verified GPIOs.
static_assert(A14 == 13 && A15 == 12 && A16 == 14 && A17 == 27,
              "Unexpected board pin mapping. Select WEMOS LOLIN32.");
static_assert(sizeof(gImage_1) == EPD_WIDTH * EPD_HEIGHT,
              "The sample must contain one palette byte per pixel (800 x 480).");

constexpr uint8_t kBusyPin = A14;   // GPIO13
constexpr uint8_t kResetPin = A15;  // GPIO12
constexpr uint8_t kDcPin = A16;     // GPIO14
constexpr uint8_t kCsPin = A17;     // GPIO27
constexpr uint8_t kSckPin = 18;
constexpr uint8_t kMosiPin = 23;

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println();
  Serial.println("[calendar] ESP32-L / GDEP073E01 starting");

  pinMode(kBusyPin, INPUT);
  pinMode(kResetPin, OUTPUT);
  pinMode(kDcPin, OUTPUT);
  pinMode(kCsPin, OUTPUT);
  digitalWrite(kResetPin, HIGH);
  digitalWrite(kDcPin, HIGH);
  digitalWrite(kCsPin, HIGH);

  // Start the bus before opening a transaction. This display only needs MOSI.
  if (!SPI.begin(kSckPin, -1, kMosiPin, kCsPin)) {
    Serial.println("[calendar] SPI could not start; display update skipped");
    return;
  }
  SPI.beginTransaction(SPISettings(10000000, MSBFIRST, SPI_MODE0));

  // Reuse the vendor's normal refresh waveform. Update only once per boot.
  Serial.println("[calendar] Initializing display");
  EPD_init();
  Serial.println("[calendar] Displaying vendor sample; waiting for refresh");
  PIC_display(gImage_1);
  Serial.println("[calendar] Refresh finished; powering off display driver");
  EPD_sleep();
  SPI.endTransaction();

  Serial.println("[calendar] Ready. Image retained; no automatic refresh scheduled");
}

void loop() {
  // Future calendar scheduling belongs here. Do not refresh on every iteration.
  delay(1000);
}

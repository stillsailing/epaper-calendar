#ifndef CALENDAR_STORE_H
#define CALENDAR_STORE_H

#include <stddef.h>
#include <stdint.h>

// Reader for the blob written by scripts/pack_calendar.py. Storage access goes
// through StoreRead so this file has no Arduino or ESP-IDF dependency.

constexpr uint32_t kFallbackDate = 0;
constexpr uint32_t kPageBytes = 800 * 480 / 2;  // Two 4-bit pixels per byte.

struct PageRef {
  uint32_t date;    // YYYYMMDD, or kFallbackDate.
  uint32_t offset;  // From the start of the blob.
  uint32_t length;  // Compressed bytes.
  uint32_t crc;     // CRC-32 of the compressed bytes.
};

using StoreRead = bool (*)(uint32_t offset, void *dst, size_t len);
using ChunkSink = void (*)(const uint8_t *data, size_t len);

// Each call returns nullptr on success or a short error message.

// Finds the page for `date`. Returns "not found" when the date is absent.
const char *storeFind(StoreRead read, uint32_t capacity, uint32_t date, PageRef &page);

// Inflates a page, passing the panel bytes to `sink` (may be nullptr to only
// verify). Succeeds only if the CRC matches and exactly kPageBytes come out.
const char *storeDecode(StoreRead read, const PageRef &page, ChunkSink sink);

#endif

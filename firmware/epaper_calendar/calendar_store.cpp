#include "calendar_store.h"

#include <stdlib.h>
#include <string.h>

// On ESP32 this is the ROM copy of miniz's inflater (esp_rom/include/miniz.h).
#include "miniz.h"

namespace {

constexpr uint16_t kVersion = 1;
constexpr uint32_t kHeaderSize = 16;
constexpr uint32_t kEntrySize = 16;
constexpr uint16_t kWidth = 800;
constexpr uint16_t kHeight = 480;
constexpr size_t kInputChunk = 4096;

uint16_t le16(const uint8_t *p) { return p[0] | (p[1] << 8); }
uint32_t le32(const uint8_t *p) {
  return p[0] | (p[1] << 8) | (p[2] << 16) | (static_cast<uint32_t>(p[3]) << 24);
}

// Standard CRC-32 (zlib.crc32), bitwise to avoid a table.
uint32_t crc32Update(uint32_t crc, const uint8_t *data, size_t len) {
  crc = ~crc;
  while (len--) {
    crc ^= *data++;
    for (int bit = 0; bit < 8; bit++) crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
  }
  return ~crc;
}

}  // namespace

const char *storeFind(StoreRead read, uint32_t capacity, uint32_t date, PageRef &page) {
  uint8_t header[kHeaderSize];
  if (capacity < kHeaderSize || !read(0, header, sizeof(header))) return "read failed";
  if (memcmp(header, "ECAL", 4) != 0) return "no calendar data";
  if (le16(header + 4) != kVersion) return "unsupported data version";
  uint16_t count = le16(header + 6);
  uint32_t total = le32(header + 12);
  if (le16(header + 8) != kWidth || le16(header + 10) != kHeight) return "wrong page size";
  if (total > capacity || kHeaderSize + count * kEntrySize > total) return "corrupt header";

  for (uint16_t i = 0; i < count; i++) {
    uint8_t entry[kEntrySize];
    if (!read(kHeaderSize + i * kEntrySize, entry, sizeof(entry))) return "read failed";
    if (le32(entry) != date) continue;
    page = {le32(entry), le32(entry + 4), le32(entry + 8), le32(entry + 12)};
    if (page.offset > total || page.length > total - page.offset) return "corrupt index";
    return nullptr;
  }
  return "not found";
}

const char *storeDecode(StoreRead read, const PageRef &page, ChunkSink sink) {
  auto *inflator = static_cast<tinfl_decompressor *>(malloc(sizeof(tinfl_decompressor)));
  auto *dict = static_cast<uint8_t *>(malloc(TINFL_LZ_DICT_SIZE));
  auto *input = static_cast<uint8_t *>(malloc(kInputChunk));
  const char *error = nullptr;
  if (!inflator || !dict || !input) {
    error = "out of memory";
  } else {
    tinfl_init(inflator);
    uint32_t consumed = 0;  // Compressed bytes read from storage.
    size_t inAvail = 0, dictOfs = 0;
    const uint8_t *inPtr = input;
    uint32_t produced = 0, crc = 0;
    for (;;) {
      if (inAvail == 0 && consumed < page.length) {
        size_t n = page.length - consumed < kInputChunk ? page.length - consumed : kInputChunk;
        if (!read(page.offset + consumed, input, n)) { error = "read failed"; break; }
        crc = crc32Update(crc, input, n);
        consumed += n;
        inPtr = input;
        inAvail = n;
      }
      size_t inBytes = inAvail, outBytes = TINFL_LZ_DICT_SIZE - dictOfs;
      mz_uint32 flags = TINFL_FLAG_PARSE_ZLIB_HEADER |
                        (consumed < page.length ? TINFL_FLAG_HAS_MORE_INPUT : 0);
      tinfl_status status =
          tinfl_decompress(inflator, inPtr, &inBytes, dict, dict + dictOfs, &outBytes, flags);
      inPtr += inBytes;
      inAvail -= inBytes;
      if (outBytes) {
        if (outBytes > kPageBytes - produced) { error = "page too large"; break; }
        if (sink) sink(dict + dictOfs, outBytes);
        produced += outBytes;
        dictOfs = (dictOfs + outBytes) & (TINFL_LZ_DICT_SIZE - 1);
      }
      if (status == TINFL_STATUS_DONE) break;
      if (status < 0) { error = "corrupt page data"; break; }
      if (status == TINFL_STATUS_NEEDS_MORE_INPUT && inAvail == 0 && consumed == page.length) {
        error = "truncated page data";
        break;
      }
    }
    if (!error && crc != page.crc) error = "CRC mismatch";
    if (!error && produced != kPageBytes) error = "page too small";
  }
  free(input);
  free(dict);
  free(inflator);
  return error;
}

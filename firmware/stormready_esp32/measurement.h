#pragma once
#include <cmath>
#include <cstddef>

namespace stormready {
constexpr float MIN_DISTANCE_MM = 100.0f;
constexpr float MAX_DISTANCE_MM = 1500.0f;
constexpr float MAX_BURST_SPREAD_MM = 15.0f;
constexpr float FLOOR_TOLERANCE_MM = 5.0f;
constexpr std::size_t BURST_SIZE = 5;

struct Distance {
  bool valid;
  float mm;
  const char* reason;
};

struct Level {
  bool valid;
  float mm;
  const char* reason;
};

// Each invocation uses only the current burst. It never reuses an old reading.
inline Distance filterBurst(const float* samples, std::size_t count) {
  float sorted[BURST_SIZE];
  std::size_t used = 0;
  for (std::size_t i = 0; i < count && i < BURST_SIZE; ++i) {
    const float value = samples[i];
    if (std::isfinite(value) && value >= MIN_DISTANCE_MM &&
        value <= MAX_DISTANCE_MM) {
      std::size_t j = used;
      while (j > 0 && sorted[j - 1] > value) {
        sorted[j] = sorted[j - 1];
        --j;
      }
      sorted[j] = value;
      ++used;
    }
  }
  if (used < 3) return {false, 0.0f, "too_few_echoes"};
  if (sorted[used - 1] - sorted[0] > MAX_BURST_SPREAD_MM)
    return {false, 0.0f, "unstable_echoes"};
  const float median = used % 2 == 1 ? sorted[used / 2]
      : (sorted[used / 2 - 1] + sorted[used / 2]) / 2.0f;
  return {true, median, "good"};
}

inline Level waterLevel(const Distance& distance, float floorDistance,
                        float maximumDepth) {
  if (!std::isfinite(floorDistance) || !std::isfinite(maximumDepth) ||
      floorDistance <= 0.0f || maximumDepth <= 0.0f)
    return {false, 0.0f, "not_calibrated"};
  if (floorDistance > MAX_DISTANCE_MM ||
      floorDistance - maximumDepth < MIN_DISTANCE_MM)
    return {false, 0.0f, "mount_too_low_or_bad_calibration"};
  if (!distance.valid) return {false, 0.0f, distance.reason};
  const float level = floorDistance - distance.mm;
  if (!std::isfinite(level) || level < -FLOOR_TOLERANCE_MM ||
      level > maximumDepth)
    return {false, 0.0f, "outside_calibrated_depth"};
  // Only a small negative empty-floor measurement is clamped to zero.
  return {true, level < 0.0f ? 0.0f : level, "good"};
}
}  // namespace stormready

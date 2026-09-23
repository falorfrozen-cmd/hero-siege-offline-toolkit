#pragma once
#include <cstdint>
namespace HeroSiege {
// ReturnSpecificStat namespace, not item-definition stat keys or UI StatId.
// Measured on exe-281751552-pe6aaa6779-111b8000: query (1,34,0,undefined,
// undefined) reaches StatMagicFind and returned 1320 on the test hero.
enum class RewardStatQuery : int32_t { MagicFind = 34 };
}

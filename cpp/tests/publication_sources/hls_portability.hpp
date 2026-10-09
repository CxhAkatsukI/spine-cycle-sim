#pragma once

// The author kernels rely on the old compiler's global unsigned-int alias.
typedef unsigned int uint;
static_assert(sizeof(uint) == 4, "ReGraph requires a 32-bit unsigned int");
static_assert(sizeof(int) == 4, "ReGraph PR requires a 32-bit signed int");

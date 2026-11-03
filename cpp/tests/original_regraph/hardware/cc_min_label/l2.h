#ifndef ORIGINAL_R_A4_CC_MIN_LABEL_L2_H
#define ORIGINAL_R_A4_CC_MIN_LABEL_L2_H

// Algorithm-only adaptation at the public fpga_application.h UDF interface.
using prop_t = unsigned int;
static_assert(sizeof(prop_t) == 4, "A4 packs sixteen 32-bit properties per word");
constexpr prop_t cc_active = 0x80000000u;
constexpr prop_t cc_label = 0x7fffffffu;
#define IS_ACTIVE_VERTEX(value) (((value) & cc_active) != 0)

inline prop_t preprocessProperty(prop_t source)
{
    // The public Little scatter calls this directly, not scatterFunc.
    return IS_ACTIVE_VERTEX(source) ? source : 0;
}

inline prop_t scatterFunc(prop_t source, prop_t)
{
    return preprocessProperty(source);
}

inline prop_t gatherFunc(prop_t original, prop_t update)
{
    if ((update & cc_active) == 0) return original;
    if ((original & cc_active) == 0) return update;
    return (update & cc_label) < (original & cc_label) ? update : original;
}

inline prop_t applyFunc(prop_t temporary, prop_t source, prop_t, unsigned int)
{
    const prop_t old_label = source & cc_label;
    return (temporary & cc_active) != 0 && (temporary & cc_label) < old_label
        ? temporary : old_label;
}

#endif

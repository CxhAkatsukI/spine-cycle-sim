#include <experimental/xrt_xclbin.h>
#include <xclbin.h>

#include <cstring>
#include <iostream>
#include <map>
#include <stdexcept>

namespace {

std::map<unsigned, const axlf_section_header*> sections(const axlf* file) {
    std::map<unsigned, const axlf_section_header*> result;
    for (unsigned i = 0; i < file->m_header.m_numSections; ++i) {
        const auto& section = file->m_sections[i];
        if (!result.emplace(section.m_sectionKind, &section).second) {
            throw std::runtime_error("duplicate section kind");
        }
    }
    return result;
}

void verify(const axlf* original, const axlf* derived) {
    const auto& before = original->m_header;
    const auto& after = derived->m_header;
    if (original->m_signature_length != -1 || derived->m_signature_length != -1 ||
        before.m_mode != after.m_mode || before.m_actionMask != after.m_actionMask ||
        before.m_featureRomTimeStamp != after.m_featureRomTimeStamp ||
        std::memcmp(before.m_interface_uuid, after.m_interface_uuid, sizeof(before.m_interface_uuid)) ||
        std::memcmp(before.m_platformVBNV, after.m_platformVBNV, sizeof(before.m_platformVBNV)) ||
        !std::memcmp(before.uuid, after.uuid, sizeof(before.uuid))) {
        throw std::runtime_error("expected unsigned images with a new UUID and the same platform and mode");
    }
    const auto source = sections(original);
    const auto copy = sections(derived);
    if (!source.contains(BITSTREAM) || !source.contains(CLOCK_FREQ_TOPOLOGY) || source.size() != copy.size()) {
        throw std::runtime_error("section inventory mismatch");
    }
    for (const auto& [kind, old] : source) {
        const auto* next = copy.at(kind);
        if (kind == CLOCK_FREQ_TOPOLOGY) {
            continue;
        }
        if (old->m_sectionSize != next->m_sectionSize ||
            std::memcmp(reinterpret_cast<const char*>(original) + old->m_sectionOffset,
                        reinterpret_cast<const char*>(derived) + next->m_sectionOffset,
                        old->m_sectionSize)) {
            throw std::runtime_error("non-clock section changed: " + std::to_string(kind));
        }
    }
    std::cout << source.size() - 1 << " non-clock sections are byte-identical\n";
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 3) {
        std::cerr << "usage: verify_clock_repackage ORIGINAL.xclbin DERIVED.xclbin\n";
        return 2;
    }
    try {
        const xrt::xclbin original(argv[1]);
        const xrt::xclbin derived(argv[2]);
        verify(original.get_axlf(), derived.get_axlf());
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
    return 0;
}

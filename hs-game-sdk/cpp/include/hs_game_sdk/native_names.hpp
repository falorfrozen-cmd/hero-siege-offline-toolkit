#pragma once
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <limits>
#include <string>
#include <string_view>
#include <vector>

namespace HeroSiege::Hooks {

// Caller supplies validated readable image spans and native function metadata.
// This search never calls or patches a resolved address. It is also used by the
// offline PE probe, so the live and disk-image searches exercise the same code.
struct NativeNameSection {
    const uint8_t* data = nullptr;
    size_t size = 0;
    bool executable = false;
    bool readable = false;
};
struct NativeFunctionRange { uintptr_t begin = 0, end = 0; };

inline uintptr_t NativeNameLeaTarget(const uint8_t* instruction) {
    // All x64 RIP-relative LEA destinations, including extended registers.
    if ((instruction[0]!=0x48 && instruction[0]!=0x4c) || instruction[1]!=0x8d ||
        (instruction[2]&0xc7)!=0x05) return 0;
    int32_t displacement=0; std::memcpy(&displacement,instruction+3,4);
    const uintptr_t next=reinterpret_cast<uintptr_t>(instruction)+7;
    const uint64_t magnitude=displacement<0 ? -static_cast<int64_t>(displacement) : displacement;
    if ((displacement<0 && magnitude>next) ||
        (displacement>=0 && magnitude>(std::numeric_limits<uintptr_t>::max)()-next)) return 0;
    return displacement<0 ? next-magnitude : next+magnitude;
}

inline bool NativeRoutineNameAt(const std::vector<NativeNameSection>& sections,uintptr_t address) {
    for (const auto& s:sections) {
        const auto begin=reinterpret_cast<uintptr_t>(s.data);
        if (!s.data || !s.readable || s.executable || address<begin || address-begin>=s.size) continue;
        const size_t offset=address-begin;
        if (s.size-offset<5 || (offset && s.data[offset-1]!=0)) return false;
        return std::memcmp(s.data+offset,"gml_",4)==0;
    }
    return false;
}

template<class Lookup>
uintptr_t ResolveNativeName(const std::vector<NativeNameSection>& sections,
    std::string_view name, Lookup lookup, std::string& note) {
    if (name.empty() || name.size()>4096 || name.find('\0')!=std::string_view::npos) {
        note="invalid routine name"; return 0;
    }
    std::vector<uintptr_t> strings, candidates;
    for (const auto& section:sections) {
        if (!section.data || !section.readable || section.executable || section.size<=name.size()) continue;
        size_t offset=0;
        const size_t last=section.size-name.size()-1;
        while (offset<=last) {
            auto* hit=static_cast<const uint8_t*>(std::memchr(section.data+offset,name[0],last-offset+1));
            if (!hit) break;
            const size_t at=static_cast<size_t>(hit-section.data);
            if ((at==0 || hit[-1]==0) && hit[name.size()]==0 && std::memcmp(hit,name.data(),name.size())==0)
                strings.push_back(reinterpret_cast<uintptr_t>(hit));
            offset=at+1;
        }
    }
    if (strings.empty()) { note="name string not found in module"; return 0; }
    for (const auto& section:sections) {
        if (!section.data || !section.readable || !section.executable || section.size<7) continue;
        for (const uint8_t rex : {0x48,0x4c}) {
          size_t offset=0;
          const size_t last=section.size-7;
          while (offset<=last) {
            auto* hit=static_cast<const uint8_t*>(std::memchr(section.data+offset,rex,last-offset+1));
            if (!hit) break;
            offset=static_cast<size_t>(hit-section.data)+1;
            const uintptr_t target=NativeNameLeaTarget(hit);
            if (!target) continue;
            const uintptr_t reference=reinterpret_cast<uintptr_t>(hit), next=reference+7;
            if (std::find(strings.begin(),strings.end(),target)==strings.end()) continue;
            const auto function=lookup(reference);
            if (!function.begin || function.begin>reference || function.end<next) continue;
            // Metadata must describe an executable span in this same image.
            bool owned=false;
            for (const auto& code:sections) {
                const auto begin=reinterpret_cast<uintptr_t>(code.data);
                if (code.data && code.readable && code.executable && function.begin>=begin &&
                    function.begin-begin<code.size && function.end>=function.begin &&
                    function.end-begin<=code.size) { owned=true; break; }
            }
            if (!owned) continue;
            // Inlined GML bodies can name another script inside a caller.
            // Its earlier routine-name marker identifies that caller: refuse
            // the inner name rather than attributing the caller to this script.
            bool innerName=false;
            for (uintptr_t at=function.begin;at<reference && at+7<=function.end;++at) {
                const auto earlier=NativeNameLeaTarget(reinterpret_cast<const uint8_t*>(at));
                if (earlier && NativeRoutineNameAt(sections,earlier)) {
                    innerName=std::find(strings.begin(),strings.end(),earlier)==strings.end();
                    break;
                }
            }
            if (!innerName) candidates.push_back(function.begin);
          }
        }
    }
    std::sort(candidates.begin(),candidates.end());
    candidates.erase(std::unique(candidates.begin(),candidates.end()),candidates.end());
    if (candidates.empty()) { note="no function metadata owns the name reference"; return 0; }
    if (candidates.size()!=1) { note="ambiguous: multiple functions reference the name"; return 0; }
    note="resolved from unique name reference and native function bounds";
    return candidates.front();
}
} // namespace HeroSiege::Hooks

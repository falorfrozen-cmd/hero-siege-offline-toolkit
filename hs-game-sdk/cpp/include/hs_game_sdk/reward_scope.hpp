#pragma once
#include <windows.h>
#include <cstdint>
#include <stdexcept>
#include <string>

// Process-local cooperation, not a plugin-symbol ABI. The game thread owns
// the short lexical scope; no flag is left active between frames or saved.
namespace HeroSiege::RewardScope {
struct State {
    uint32_t version;
    uint32_t forgePactReady;
    DWORD ownerThread;
    uint32_t depth;
    double forgePactXp;
    double nativeDropBase[20 * 256]; // zero means not observed
};
class Mapping {
    HANDLE handle_{};
    State* state_{};
public:
    Mapping() {
        const auto name=L"Local\\HeroSiegeRewardScope-v1-"+std::to_wstring(GetCurrentProcessId());
        handle_=CreateFileMappingW(INVALID_HANDLE_VALUE,nullptr,PAGE_READWRITE,0,sizeof(State),name.c_str());
        if(handle_)state_=static_cast<State*>(MapViewOfFile(handle_,FILE_MAP_ALL_ACCESS,0,0,sizeof(State)));
        if(state_ && !state_->version)state_->version=1;
    }
    ~Mapping(){if(state_)UnmapViewOfFile(state_);if(handle_)CloseHandle(handle_);}
    State* get()const{return state_ && state_->version==1 ? state_ : nullptr;}
};
inline State* Get(){static Mapping mapping;return mapping.get();}
inline bool Active(){const auto* s=Get();return s && s->depth && s->ownerThread==GetCurrentThreadId();}
inline void RegisterForgePact(){auto* s=Get();if(s){s->forgePactXp=1;s->forgePactReady=1;}}
inline void SetForgePactXp(double n){auto* s=Get();if(s)s->forgePactXp=n;}
inline void PublishBase(int category,int index,double base){
    auto* s=Get();if(s && category>=0 && category<20 && index>=0 && index<256 && base>0)
        s->nativeDropBase[category*256+index]=base;
}
class Guard {
    State* state_;
public:
    Guard():state_(Get()){
        if(!state_ || (state_->depth && state_->ownerThread!=GetCurrentThreadId()))
            throw std::runtime_error("reward scope unavailable");
        state_->ownerThread=GetCurrentThreadId();++state_->depth;
    }
    ~Guard(){if(!--state_->depth)state_->ownerThread=0;}
    Guard(const Guard&)=delete;
    Guard& operator=(const Guard&)=delete;
};
}

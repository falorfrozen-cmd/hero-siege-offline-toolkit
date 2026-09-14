// Minimal stand-in for YYToolkit's YYTK_Shared.hpp.
//
// Its only job is to let the real hs-game-sdk headers compile unmodified while
// a test supplies controlled responses: the SDK detects YYToolkit with
// __has_include(<YYToolkit/YYTK_Shared.hpp>), so putting this on the include
// path in front is enough to define HS_SDK_HAS_YYTK and exercise the production
// code paths.
//
// Only the surface hs-game-sdk touches is declared, and RValue is a simple
// tagged value the harness can build by hand rather than YYToolkit's real
// layout. Nothing here is derived from YYToolkit's implementation.
#pragma once

// The real chain is YYTK_Shared.hpp -> YYTK_Shared_Base.hpp -> Aurie/shared.hpp,
// which is why hooks.hpp can reach MmCreateHook without including Aurie itself.
#include <Aurie/shared.hpp>

#include <map>
#include <memory>
#include <string>
#include <vector>

namespace YYTK {

enum RValueKind : int {
    VALUE_REAL = 0,
    VALUE_STRING = 1,
    VALUE_ARRAY = 2,
    VALUE_UNDEFINED = 5,
    VALUE_OBJECT = 6,
    VALUE_INT32 = 7,
    VALUE_INT64 = 8,
    VALUE_BOOL = 13,
    // A live instance reference. This runner hands one back for the local
    // player (MEASURED 2026-09-10, see ForgePact ModuleMain.cpp's
    // HhResolveLocalPlayer), so the SDK has to accept it wherever it accepts
    // an instance. The value matches YYToolkit's own enum.
    VALUE_REF = 15,
};

struct RValue;

/// Stand-in for a GML struct: named fields the harness fills in.
using FakeStruct = std::map<std::string, RValue>;

struct RValue {
    RValueKind m_Kind = VALUE_UNDEFINED;
    double m_Real = 0.0;
    std::string m_String;
    /// Non-null for VALUE_OBJECT. Points at the FakeStruct below.
    void* m_Object = nullptr;

    std::shared_ptr<FakeStruct> m_Struct;
    std::shared_ptr<std::vector<RValue>> m_Elements;

    RValue() = default;

    explicit RValue(double value) : m_Kind(VALUE_REAL), m_Real(value) {}
    explicit RValue(int value) : m_Kind(VALUE_REAL), m_Real(static_cast<double>(value)) {}
    explicit RValue(bool value) : m_Kind(VALUE_BOOL), m_Real(value ? 1.0 : 0.0) {}
    explicit RValue(std::string value) : m_Kind(VALUE_STRING), m_String(std::move(value)) {}

    [[nodiscard]] double ToDouble() const {
        if (m_Kind == VALUE_STRING) return 0.0;
        return m_Real;
    }

    [[nodiscard]] bool ToBoolean() const {
        if (m_Kind == VALUE_UNDEFINED) return false;
        if (m_Kind == VALUE_STRING) return !m_String.empty();
        return m_Real != 0.0;
    }

    /// Builds a VALUE_OBJECT holding the given fields.
    static RValue Struct(FakeStruct fields) {
        RValue value;
        value.m_Kind = VALUE_OBJECT;
        value.m_Struct = std::make_shared<FakeStruct>(std::move(fields));
        value.m_Object = value.m_Struct.get();
        return value;
    }

    /// Builds a VALUE_ARRAY holding the given elements.
    static RValue Array(std::vector<RValue> elements) {
        RValue value;
        value.m_Kind = VALUE_ARRAY;
        value.m_Elements = std::make_shared<std::vector<RValue>>(std::move(elements));
        return value;
    }
};

struct CInstance {
    int placeholder = 0;
};

using PFUNC_YYGMLScript = RValue& (*)(CInstance*, CInstance*, RValue&, int, RValue**);

struct CScriptFunctions {
    PFUNC_YYGMLScript m_ScriptFunction = nullptr;
};

struct CScript {
    CScriptFunctions* m_Functions = nullptr;
};

struct YYTKInterface {
    virtual ~YYTKInterface() = default;

    virtual RValue CallBuiltin(std::string_view name, std::vector<RValue> args) = 0;
    virtual RValue CallGameScript(std::string name, const std::vector<RValue>& args) = 0;
    virtual ::Aurie::AurieStatus GetGlobalInstance(CInstance** outInstance) = 0;
    virtual ::Aurie::AurieStatus GetNamedRoutinePointer(const char* name, PVOID* outPointer) = 0;
};

} // namespace YYTK

#include "UnrealAssetToolMotionWarpingCommandlet.h"

#include "Animation/AnimNotifies/AnimNotifyState.h"
#include "Animation/AnimSequenceBase.h"
#include "AssetRegistry/AssetData.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "HAL/FileManager.h"
#include "Json.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/UnrealType.h"

namespace UnrealAssetToolMotionWarping
{
constexpr int32 SchemaVersion = 1;
constexpr int32 MaxExportChars = 32768;
static const TCHAR* MotionWarpingNotifyClassPath = TEXT("/Script/MotionWarping.AnimNotifyState_MotionWarping");

struct FCounts
{
    int64 AnimationCandidates = 0;
    int64 AnimationAssetsLoaded = 0;
    int64 LoadFailures = 0;
    int64 MotionWarpingWindows = 0;
    int64 Modifiers = 0;
    int64 ModifierProperties = 0;
    int64 WindowsWithoutModifier = 0;
};

class FJsonlWriter
{
public:
    bool Open(const FString& Filename)
    {
        IFileManager::Get().MakeDirectory(*FPaths::GetPath(Filename), true);
        Archive.Reset(IFileManager::Get().CreateFileWriter(*Filename));
        return Archive.IsValid();
    }

    bool Write(const TSharedRef<FJsonObject>& Object)
    {
        if (!Archive.IsValid()) return false;
        FString Line;
        const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
            TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Line);
        if (!FJsonSerializer::Serialize(Object, Writer)) return false;
        Line.AppendChar(TEXT('\n'));
        FTCHARToUTF8 Utf8(*Line);
        Archive->Serialize((void*)Utf8.Get(), Utf8.Length());
        return !Archive->IsError();
    }

    bool Close()
    {
        if (!Archive.IsValid()) return true;
        const bool bClosed = Archive->Close();
        const bool bOk = bClosed && !Archive->IsError();
        Archive.Reset();
        return bOk;
    }

    ~FJsonlWriter() { Close(); }

private:
    TUniquePtr<FArchive> Archive;
};

struct FWriters
{
    FJsonlWriter Windows;
    FJsonlWriter Modifiers;
    FJsonlWriter Properties;

    bool Open(const FString& OutputDir)
    {
        return Windows.Open(FPaths::Combine(OutputDir, TEXT("motion_warping_windows.jsonl"))) &&
            Modifiers.Open(FPaths::Combine(OutputDir, TEXT("motion_warping_modifiers.jsonl"))) &&
            Properties.Open(FPaths::Combine(OutputDir, TEXT("motion_warping_modifier_properties.jsonl")));
    }

    bool Close()
    {
        bool bOk = true;
        bOk = Windows.Close() && bOk;
        bOk = Modifiers.Close() && bOk;
        bOk = Properties.Close() && bOk;
        return bOk;
    }
};

static FString NormalizeAbsolutePath(const FString& InPath)
{
    FString Path = FPaths::ConvertRelativePathToFull(InPath);
    FPaths::NormalizeFilename(Path);
    FPaths::CollapseRelativeDirectories(Path);
    return Path;
}

static bool IsInsideDirectory(const FString& File, const FString& Directory)
{
    FString NormalizedFile = NormalizeAbsolutePath(File);
    FString NormalizedDirectory = NormalizeAbsolutePath(Directory);
    if (!NormalizedDirectory.EndsWith(TEXT("/"))) NormalizedDirectory.AppendChar(TEXT('/'));
    return NormalizedFile.StartsWith(NormalizedDirectory, ESearchCase::IgnoreCase);
}

static bool AssetInScope(const FAssetData& Asset, const FString& ProjectDir, bool bIncludeEngine)
{
    if (bIncludeEngine) return true;
    FString Filename;
    FPackageName::DoesPackageExist(Asset.PackageName.ToString(), &Filename, false);
    return !Filename.IsEmpty() && IsInsideDirectory(Filename, ProjectDir);
}

static bool ShouldCaptureAuthoredProperty(const FProperty* Property)
{
    if (!Property || !Property->HasAnyPropertyFlags(CPF_Edit))
    {
        return false;
    }
    constexpr EPropertyFlags Rejected =
        CPF_Transient | CPF_DuplicateTransient | CPF_NonPIEDuplicateTransient |
        CPF_Deprecated | CPF_SkipSerialization;
    return !Property->HasAnyPropertyFlags(Rejected);
}

static FString ExportProperty(const FProperty* Property, const void* ValuePtr, UObject* Owner)
{
    if (!Property || !ValuePtr) return FString();
    FString Value;
    Property->ExportTextItem_Direct(Value, ValuePtr, nullptr, Owner, PPF_None, nullptr);
    if (Value.Len() > MaxExportChars)
    {
        Value.LeftInline(MaxExportChars, EAllowShrinking::No);
    }
    return Value;
}

static UObject* ObjectField(UObject* Object, const TCHAR* Name)
{
    if (!Object) return nullptr;
    const FObjectPropertyBase* Property =
        CastField<FObjectPropertyBase>(Object->GetClass()->FindPropertyByName(FName(Name)));
    if (!Property) return nullptr;
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
    return ValuePtr ? Property->GetObjectPropertyValue(ValuePtr) : nullptr;
}

static FString PropertyText(UObject* Object, const TCHAR* Name)
{
    if (!Object) return FString();
    const FProperty* Property = Object->GetClass()->FindPropertyByName(FName(Name));
    if (!Property) return FString();
    return ExportProperty(Property, Property->ContainerPtrToValuePtr<void>(Object), Object);
}

static bool PropertyBool(UObject* Object, const TCHAR* Name, bool& OutValue)
{
    if (!Object) return false;
    const FBoolProperty* Property =
        CastField<FBoolProperty>(Object->GetClass()->FindPropertyByName(FName(Name)));
    if (!Property) return false;
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
    if (!ValuePtr) return false;
    OutValue = Property->GetPropertyValue(ValuePtr);
    return true;
}

static bool WriteModifierProperties(
    UObject* Modifier,
    const FString& AssetPath,
    int32 NotifyIndex,
    const FString& NotifyStatePath,
    FWriters& Writers,
    FCounts& Counts)
{
    if (!Modifier) return true;

    for (UClass* Class = Modifier->GetClass(); Class && Class != UObject::StaticClass(); Class = Class->GetSuperClass())
    {
        for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
        {
            const FProperty* Property = *It;
            if (!ShouldCaptureAuthoredProperty(Property)) continue;

            for (int32 StaticIndex = 0; StaticIndex < Property->ArrayDim; ++StaticIndex)
            {
                const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Modifier, StaticIndex);
                TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
                Row->SetStringField(TEXT("asset_path"), AssetPath);
                Row->SetNumberField(TEXT("notify_index"), NotifyIndex);
                Row->SetStringField(TEXT("notify_state_path"), NotifyStatePath);
                Row->SetStringField(TEXT("modifier_path"), Modifier->GetPathName());
                Row->SetStringField(TEXT("modifier_class"), Modifier->GetClass()->GetPathName());
                Row->SetStringField(TEXT("declaring_type"), Class->GetPathName());
                Row->SetStringField(TEXT("property_name"), Property->GetName());
                Row->SetNumberField(TEXT("static_index"), StaticIndex);
                Row->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
                Row->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
                Row->SetStringField(TEXT("value"), ExportProperty(Property, ValuePtr, Modifier));

                if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
                {
                    UObject* Target = ObjectProperty->GetObjectPropertyValue(ValuePtr);
                    Row->SetStringField(TEXT("target_path"), Target ? Target->GetPathName() : FString());
                    Row->SetStringField(TEXT("target_class"), Target ? Target->GetClass()->GetPathName() : FString());
                }

                if (!Writers.Properties.Write(Row)) return false;
                ++Counts.ModifierProperties;
            }
        }
    }
    return true;
}

static void AddKnownWarpFields(UObject* Modifier, const TSharedRef<FJsonObject>& Row)
{
    if (!Modifier) return;

    Row->SetStringField(TEXT("warp_target_name"), PropertyText(Modifier, TEXT("WarpTargetName")));
    Row->SetStringField(TEXT("warp_point_anim_provider"), PropertyText(Modifier, TEXT("WarpPointAnimProvider")));
    Row->SetStringField(TEXT("warp_point_anim_bone_name"), PropertyText(Modifier, TEXT("WarpPointAnimBoneName")));
    Row->SetStringField(TEXT("warp_point_anim_transform"), PropertyText(Modifier, TEXT("WarpPointAnimTransform")));
    Row->SetStringField(TEXT("rotation_type"), PropertyText(Modifier, TEXT("RotationType")));
    Row->SetStringField(TEXT("rotation_method"), PropertyText(Modifier, TEXT("RotationMethod")));
    Row->SetStringField(TEXT("warp_rotation_time_multiplier"), PropertyText(Modifier, TEXT("WarpRotationTimeMultiplier")));
    Row->SetStringField(TEXT("warp_max_rotation_rate"), PropertyText(Modifier, TEXT("WarpMaxRotationRate")));
    Row->SetStringField(TEXT("additional_rotation_offset"), PropertyText(Modifier, TEXT("AdditionalRotationOffset")));
    Row->SetStringField(TEXT("add_translation_easing_func"), PropertyText(Modifier, TEXT("AddTranslationEasingFunc")));

    if (UObject* Curve = ObjectField(Modifier, TEXT("AddTranslationEasingCurve")))
    {
        Row->SetStringField(TEXT("add_translation_easing_curve"), Curve->GetPathName());
        Row->SetStringField(TEXT("add_translation_easing_curve_class"), Curve->GetClass()->GetPathName());
    }
    else
    {
        Row->SetStringField(TEXT("add_translation_easing_curve"), FString());
        Row->SetStringField(TEXT("add_translation_easing_curve_class"), FString());
    }

    struct FBoolField
    {
        const TCHAR* PropertyName;
        const TCHAR* JsonName;
    };
    static const FBoolField BoolFields[] = {
        { TEXT("bWarpTranslation"), TEXT("warp_translation") },
        { TEXT("bIgnoreZAxis"), TEXT("ignore_z_axis") },
        { TEXT("bWarpRotation"), TEXT("warp_rotation") },
        { TEXT("bWarpToFeetLocation"), TEXT("warp_to_feet_location") },
        { TEXT("bSubtractRemainingRootMotion"), TEXT("subtract_remaining_root_motion") },
    };
    for (const FBoolField& Field : BoolFields)
    {
        bool Value = false;
        if (PropertyBool(Modifier, Field.PropertyName, Value))
        {
            Row->SetBoolField(Field.JsonName, Value);
        }
    }
}

static bool WriteWindow(
    UAnimSequenceBase* Sequence,
    const FAssetData& Asset,
    int32 NotifyIndex,
    const FAnimNotifyEvent& Event,
    UAnimNotifyState* NotifyState,
    FWriters& Writers,
    FCounts& Counts)
{
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    UObject* Modifier = ObjectField(NotifyState, TEXT("RootMotionModifier"));

    TSharedRef<FJsonObject> Window = MakeShared<FJsonObject>();
    Window->SetStringField(TEXT("asset_path"), AssetPath);
    Window->SetStringField(TEXT("asset_class"), Sequence ? Sequence->GetClass()->GetPathName() : FString());
    Window->SetNumberField(TEXT("notify_index"), NotifyIndex);
    Window->SetStringField(TEXT("notify_guid"), Event.Guid.ToString(EGuidFormats::DigitsWithHyphensLower));
    Window->SetStringField(TEXT("notify_state_path"), NotifyState ? NotifyState->GetPathName() : FString());
    Window->SetStringField(TEXT("notify_state_class"), NotifyState ? NotifyState->GetClass()->GetPathName() : FString());
    Window->SetNumberField(TEXT("trigger_time"), Event.GetTriggerTime());
    Window->SetNumberField(TEXT("end_trigger_time"), Event.GetEndTriggerTime());
    Window->SetNumberField(TEXT("duration"), Event.GetDuration());
    Window->SetNumberField(TEXT("track_index"), Event.TrackIndex);
    Window->SetStringField(TEXT("modifier_path"), Modifier ? Modifier->GetPathName() : FString());
    Window->SetStringField(TEXT("modifier_class"), Modifier ? Modifier->GetClass()->GetPathName() : FString());
    Window->SetBoolField(TEXT("modifier_present"), Modifier != nullptr);
    if (!Writers.Windows.Write(Window)) return false;
    ++Counts.MotionWarpingWindows;

    if (!Modifier)
    {
        ++Counts.WindowsWithoutModifier;
        return true;
    }

    TSharedRef<FJsonObject> ModifierRow = MakeShared<FJsonObject>();
    ModifierRow->SetStringField(TEXT("asset_path"), AssetPath);
    ModifierRow->SetNumberField(TEXT("notify_index"), NotifyIndex);
    ModifierRow->SetStringField(TEXT("notify_state_path"), NotifyState->GetPathName());
    ModifierRow->SetStringField(TEXT("modifier_path"), Modifier->GetPathName());
    ModifierRow->SetStringField(TEXT("modifier_class"), Modifier->GetClass()->GetPathName());
    ModifierRow->SetStringField(TEXT("outer_path"), Modifier->GetOuter() ? Modifier->GetOuter()->GetPathName() : FString());
    ModifierRow->SetStringField(TEXT("outer_class"), Modifier->GetOuter() ? Modifier->GetOuter()->GetClass()->GetPathName() : FString());
    ModifierRow->SetBoolField(TEXT("is_template"), true);
    AddKnownWarpFields(Modifier, ModifierRow);

    if (!Writers.Modifiers.Write(ModifierRow)) return false;
    ++Counts.Modifiers;
    return WriteModifierProperties(Modifier, AssetPath, NotifyIndex, NotifyState->GetPathName(), Writers, Counts);
}

static bool WriteManifest(
    const FString& OutputDir,
    const FCounts& Counts,
    bool bSuccess,
    const FString& Error,
    bool bIncludeEngine)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetNumberField(TEXT("schema_version"), SchemaVersion);
    Root->SetBoolField(TEXT("success"), bSuccess);
    Root->SetStringField(TEXT("error"), Error);
    Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetBoolField(TEXT("include_engine"), bIncludeEngine);
    Root->SetBoolField(TEXT("diagnostic_only"), true);
    Root->SetBoolField(TEXT("semantic_promotion"), false);
    Root->SetBoolField(TEXT("schema_promotion"), false);
    Root->SetBoolField(TEXT("runtime_state_captured"), false);
    Root->SetBoolField(TEXT("live_warp_targets_captured"), false);
    Root->SetBoolField(TEXT("active_root_motion_modifiers_captured"), false);
    Root->SetBoolField(TEXT("root_motion_evaluated"), false);
    Root->SetBoolField(TEXT("maps_loaded"), false);
    Root->SetBoolField(TEXT("motion_warping_module_linked"), false);

    TSharedRef<FJsonObject> CountJson = MakeShared<FJsonObject>();
    CountJson->SetNumberField(TEXT("animation_candidates"), Counts.AnimationCandidates);
    CountJson->SetNumberField(TEXT("animation_assets_loaded"), Counts.AnimationAssetsLoaded);
    CountJson->SetNumberField(TEXT("load_failures"), Counts.LoadFailures);
    CountJson->SetNumberField(TEXT("motion_warping_windows"), Counts.MotionWarpingWindows);
    CountJson->SetNumberField(TEXT("modifiers"), Counts.Modifiers);
    CountJson->SetNumberField(TEXT("modifier_properties"), Counts.ModifierProperties);
    CountJson->SetNumberField(TEXT("windows_without_modifier"), Counts.WindowsWithoutModifier);
    Root->SetObjectField(TEXT("counts"), CountJson);

    FString Text;
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Text);
    if (!FJsonSerializer::Serialize(Root, Writer)) return false;
    Text.AppendChar(TEXT('\n'));
    return FFileHelper::SaveStringToFile(
        Text,
        *FPaths::Combine(OutputDir, TEXT("motion_warping_capture_manifest.json")),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

static bool RunCapture(
    const FString& OutputDir,
    bool bIncludeEngine,
    FCounts& Counts,
    FString& Error)
{
    FWriters Writers;
    if (!Writers.Open(OutputDir))
    {
        Error = TEXT("could not create Motion Warping capture outputs");
        return false;
    }

    IAssetRegistry& Registry =
        FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get();
    Registry.WaitForCompletion();

    TArray<FAssetData> Assets;
    Registry.GetAssetsByClass(UAnimSequenceBase::StaticClass()->GetClassPathName(), Assets, true);

    const FString ProjectDir = FPaths::ProjectDir();
    Assets.RemoveAll([&](const FAssetData& Asset)
    {
        return !AssetInScope(Asset, ProjectDir, bIncludeEngine);
    });
    Assets.Sort([](const FAssetData& A, const FAssetData& B)
    {
        const FString AP = A.GetSoftObjectPath().ToString();
        const FString BP = B.GetSoftObjectPath().ToString();
        const int32 Folded = AP.Compare(BP, ESearchCase::IgnoreCase);
        return Folded == 0 ? AP.Compare(BP, ESearchCase::CaseSensitive) < 0 : Folded < 0;
    });
    Counts.AnimationCandidates = Assets.Num();

    for (const FAssetData& Asset : Assets)
    {
        UAnimSequenceBase* Sequence = Cast<UAnimSequenceBase>(Asset.GetAsset());
        if (!Sequence)
        {
            ++Counts.LoadFailures;
            continue;
        }
        ++Counts.AnimationAssetsLoaded;

        for (int32 NotifyIndex = 0; NotifyIndex < Sequence->Notifies.Num(); ++NotifyIndex)
        {
            const FAnimNotifyEvent& Event = Sequence->Notifies[NotifyIndex];
            UAnimNotifyState* NotifyState = Event.NotifyStateClass.Get();
            if (!NotifyState || NotifyState->GetClass()->GetPathName() != MotionWarpingNotifyClassPath)
            {
                continue;
            }

            if (!WriteWindow(Sequence, Asset, NotifyIndex, Event, NotifyState, Writers, Counts))
            {
                Error = FString::Printf(
                    TEXT("failed writing Motion Warping window: %s notify %d"),
                    *Asset.GetSoftObjectPath().ToString(),
                    NotifyIndex);
                Writers.Close();
                return false;
            }
        }
    }

    if (!Writers.Close())
    {
        Error = TEXT("failed closing Motion Warping capture outputs");
        return false;
    }
    return true;
}
} // namespace UnrealAssetToolMotionWarping

UUnrealAssetToolMotionWarpingCommandlet::UUnrealAssetToolMotionWarpingCommandlet()
{
    IsClient = false;
    IsEditor = true;
    IsServer = false;
    LogToConsole = true;
    ShowErrorCount = true;
}

int32 UUnrealAssetToolMotionWarpingCommandlet::Main(const FString& Params)
{
    using namespace UnrealAssetToolMotionWarping;

    FString OutputDir;
    FParse::Value(*Params, TEXT("Output="), OutputDir);
    if (OutputDir.IsEmpty())
    {
        OutputDir = FPaths::Combine(FPaths::ProjectDir(), TEXT(".uatool"), TEXT("motion-warping-native-capture"));
    }
    else if (FPaths::IsRelative(OutputDir))
    {
        OutputDir = FPaths::Combine(FPaths::ProjectDir(), OutputDir);
    }
    OutputDir = NormalizeAbsolutePath(OutputDir);
    IFileManager::Get().MakeDirectory(*OutputDir, true);

    const bool bIncludeEngine = FParse::Param(*Params, TEXT("IncludeEngine"));
    FCounts Counts;
    FString Error;
    const bool bSuccess = RunCapture(OutputDir, bIncludeEngine, Counts, Error);
    if (!WriteManifest(OutputDir, Counts, bSuccess, Error, bIncludeEngine))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolMotionWarping: failed writing capture manifest"));
        return 2;
    }
    if (!bSuccess)
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolMotionWarping: %s"), *Error);
        return 1;
    }

    UE_LOG(
        LogTemp,
        Display,
        TEXT("UnrealAssetToolMotionWarping captured %lld windows, %lld modifiers, %lld authored properties from %lld animation assets"),
        Counts.MotionWarpingWindows,
        Counts.Modifiers,
        Counts.ModifierProperties,
        Counts.AnimationAssetsLoaded);

    return Counts.LoadFailures == 0 ? 0 : 3;
}

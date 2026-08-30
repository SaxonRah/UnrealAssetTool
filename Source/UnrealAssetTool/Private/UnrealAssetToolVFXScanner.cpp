#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "HAL/FileManager.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/CommandLine.h"
#include "Misc/CoreDelegates.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "UObject/SoftObjectPtr.h"
#include "UObject/UnrealType.h"

namespace UnrealAssetToolVFX
{
static constexpr int32 VFXSchemaVersion = 1;
static constexpr int32 MaxExportChars = 65536;
static constexpr int32 MaxReferenceDepth = 8;
static constexpr int32 MaxReferencesPerOwner = 4096;

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
        if (!Archive.IsValid())
        {
            return false;
        }
        FString Line;
        const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
            TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Line);
        if (!FJsonSerializer::Serialize(Object, Writer))
        {
            return false;
        }
        Line.AppendChar(TEXT('\n'));
        FTCHARToUTF8 Utf8(*Line);
        Archive->Serialize((void*)Utf8.Get(), Utf8.Length());
        return !Archive->IsError();
    }

private:
    TUniquePtr<FArchive> Archive;
};

struct FCounts
{
    int64 Assets = 0;
    int64 Properties = 0;
    int64 References = 0;
    int64 NiagaraSystems = 0;
    int64 NiagaraSystemEmitters = 0;
    int64 NiagaraEmitters = 0;
    int64 NiagaraEmitterVersions = 0;
    int64 NiagaraRenderers = 0;
    int64 NiagaraSimulationStages = 0;
    int64 NiagaraScripts = 0;
    int64 NiagaraDataChannels = 0;
    int64 NiagaraDataChannelVariables = 0;
    int64 NiagaraEffectTypes = 0;
    int64 CascadeSystems = 0;
    int64 CascadeEmitters = 0;
    int64 CascadeLODs = 0;
    int64 CascadeModules = 0;
};

struct FWriters
{
    FJsonlWriter Assets;
    FJsonlWriter Properties;
    FJsonlWriter References;
    FJsonlWriter NiagaraSystems;
    FJsonlWriter NiagaraSystemEmitters;
    FJsonlWriter NiagaraEmitters;
    FJsonlWriter NiagaraEmitterVersions;
    FJsonlWriter NiagaraRenderers;
    FJsonlWriter NiagaraSimulationStages;
    FJsonlWriter NiagaraScripts;
    FJsonlWriter NiagaraDataChannels;
    FJsonlWriter NiagaraDataChannelVariables;
    FJsonlWriter NiagaraEffectTypes;
    FJsonlWriter CascadeSystems;
    FJsonlWriter CascadeEmitters;
    FJsonlWriter CascadeLODs;
    FJsonlWriter CascadeModules;

    bool Open(const FString& OutputDir)
    {
        return Assets.Open(FPaths::Combine(OutputDir, TEXT("vfx_assets.jsonl"))) &&
            Properties.Open(FPaths::Combine(OutputDir, TEXT("vfx_properties.jsonl"))) &&
            References.Open(FPaths::Combine(OutputDir, TEXT("vfx_references.jsonl"))) &&
            NiagaraSystems.Open(FPaths::Combine(OutputDir, TEXT("niagara_systems.jsonl"))) &&
            NiagaraSystemEmitters.Open(FPaths::Combine(OutputDir, TEXT("niagara_system_emitters.jsonl"))) &&
            NiagaraEmitters.Open(FPaths::Combine(OutputDir, TEXT("niagara_emitters.jsonl"))) &&
            NiagaraEmitterVersions.Open(FPaths::Combine(OutputDir, TEXT("niagara_emitter_versions.jsonl"))) &&
            NiagaraRenderers.Open(FPaths::Combine(OutputDir, TEXT("niagara_renderers.jsonl"))) &&
            NiagaraSimulationStages.Open(FPaths::Combine(OutputDir, TEXT("niagara_simulation_stages.jsonl"))) &&
            NiagaraScripts.Open(FPaths::Combine(OutputDir, TEXT("niagara_scripts.jsonl"))) &&
            NiagaraDataChannels.Open(FPaths::Combine(OutputDir, TEXT("niagara_data_channels.jsonl"))) &&
            NiagaraDataChannelVariables.Open(FPaths::Combine(OutputDir, TEXT("niagara_data_channel_variables.jsonl"))) &&
            NiagaraEffectTypes.Open(FPaths::Combine(OutputDir, TEXT("niagara_effect_types.jsonl"))) &&
            CascadeSystems.Open(FPaths::Combine(OutputDir, TEXT("cascade_systems.jsonl"))) &&
            CascadeEmitters.Open(FPaths::Combine(OutputDir, TEXT("cascade_emitters.jsonl"))) &&
            CascadeLODs.Open(FPaths::Combine(OutputDir, TEXT("cascade_lods.jsonl"))) &&
            CascadeModules.Open(FPaths::Combine(OutputDir, TEXT("cascade_modules.jsonl")));
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
    FString F = NormalizeAbsolutePath(File);
    FString D = NormalizeAbsolutePath(Directory);
    if (!D.EndsWith(TEXT("/")))
    {
        D.AppendChar(TEXT('/'));
    }
    return F.StartsWith(D, ESearchCase::IgnoreCase);
}

static bool ShouldInspectProperty(const FProperty* Property)
{
    if (!Property)
    {
        return false;
    }
    constexpr EPropertyFlags Rejected =
        CPF_Transient | CPF_DuplicateTransient | CPF_NonPIEDuplicateTransient | CPF_Deprecated | CPF_SkipSerialization;
    return !Property->HasAnyPropertyFlags(Rejected);
}

static FString ExportProperty(const FProperty* Property, const void* ValuePtr, UObject* Owner, bool& bTruncated)
{
    bTruncated = false;
    if (!Property || !ValuePtr)
    {
        return FString();
    }
    FString Value;
    Property->ExportTextItem_Direct(Value, ValuePtr, nullptr, Owner, PPF_None, nullptr);
    if (Value.Len() > MaxExportChars)
    {
        Value.LeftInline(MaxExportChars, EAllowShrinking::No);
        bTruncated = true;
    }
    return Value;
}

static FString ExportField(UStruct* Struct, const void* StructValue, const FName FieldName, UObject* Owner)
{
    if (!Struct || !StructValue)
    {
        return FString();
    }
    const FProperty* Property = Struct->FindPropertyByName(FieldName);
    if (!Property)
    {
        return FString();
    }
    bool bTruncated = false;
    return ExportProperty(Property, Property->ContainerPtrToValuePtr<void>(StructValue), Owner, bTruncated);
}

static FString ExportField(UObject* Object, const FName FieldName)
{
    return Object ? ExportField(Object->GetClass(), Object, FieldName, Object) : FString();
}

static UObject* GetObjectField(UStruct* Struct, const void* StructValue, const FName FieldName)
{
    if (!Struct || !StructValue)
    {
        return nullptr;
    }
    const FObjectPropertyBase* Property = CastField<FObjectPropertyBase>(Struct->FindPropertyByName(FieldName));
    if (!Property)
    {
        return nullptr;
    }
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(StructValue);
    return ValuePtr ? Property->GetObjectPropertyValue(ValuePtr) : nullptr;
}

static UObject* GetObjectField(UObject* Object, const FName FieldName)
{
    return Object ? GetObjectField(Object->GetClass(), Object, FieldName) : nullptr;
}

static FString GetNameField(UStruct* Struct, const void* StructValue, const FName FieldName, UObject* Owner)
{
    if (!Struct || !StructValue)
    {
        return FString();
    }
    if (const FNameProperty* Property = CastField<FNameProperty>(Struct->FindPropertyByName(FieldName)))
    {
        const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(StructValue);
        return ValuePtr ? Property->GetPropertyValue(ValuePtr).ToString() : FString();
    }
    FString Value = ExportField(Struct, StructValue, FieldName, Owner);
    Value.TrimStartAndEndInline();
    if (Value.StartsWith(TEXT("\"") ) && Value.EndsWith(TEXT("\"")) && Value.Len() >= 2)
    {
        Value = Value.Mid(1, Value.Len() - 2);
    }
    return Value;
}

static bool GetBoolField(UStruct* Struct, const void* StructValue, const FName FieldName, bool& bFound)
{
    bFound = false;
    if (!Struct || !StructValue)
    {
        return false;
    }
    if (const FBoolProperty* Property = CastField<FBoolProperty>(Struct->FindPropertyByName(FieldName)))
    {
        const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(StructValue);
        if (ValuePtr)
        {
            bFound = true;
            return Property->GetPropertyValue(ValuePtr);
        }
    }
    return false;
}

static int32 CountArray(UStruct* Struct, const void* StructValue, const FName FieldName)
{
    if (!Struct || !StructValue)
    {
        return 0;
    }
    FArrayProperty* Array = CastField<FArrayProperty>(Struct->FindPropertyByName(FieldName));
    const void* ValuePtr = Array ? Array->ContainerPtrToValuePtr<void>(StructValue) : nullptr;
    return Array && ValuePtr ? FScriptArrayHelper(Array, ValuePtr).Num() : 0;
}

static bool WriteProperties(UObject* Object, const FString& AssetPath, const FString& OwnerKind, FWriters& Writers, FCounts& Counts)
{
    if (!Object)
    {
        return true;
    }
    TSet<FString> Seen;
    for (UClass* Class = Object->GetClass(); Class && Class != UObject::StaticClass(); Class = Class->GetSuperClass())
    {
        for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
        {
            FProperty* Property = *It;
            if (!ShouldInspectProperty(Property))
            {
                continue;
            }
            const FString Key = Class->GetPathName() + TEXT("::") + Property->GetName();
            if (Seen.Contains(Key))
            {
                continue;
            }
            Seen.Add(Key);
            bool bTruncated = false;
            const FString Value = ExportProperty(Property, Property->ContainerPtrToValuePtr<void>(Object), Object, bTruncated);
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("asset_path"), AssetPath);
            Row->SetStringField(TEXT("owner_path"), Object->GetPathName());
            Row->SetStringField(TEXT("owner_kind"), OwnerKind);
            Row->SetStringField(TEXT("owner_class"), Object->GetClass()->GetPathName());
            Row->SetStringField(TEXT("declaring_type"), Class->GetPathName());
            Row->SetStringField(TEXT("property_name"), Property->GetName());
            Row->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
            Row->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
            Row->SetStringField(TEXT("value"), Value);
            Row->SetBoolField(TEXT("truncated"), bTruncated);
            if (!Writers.Properties.Write(Row))
            {
                return false;
            }
            ++Counts.Properties;
        }
    }
    return true;
}

struct FReferenceContext
{
    FString AssetPath;
    FString OwnerPath;
    FString OwnerKind;
    FString RootProperty;
    int32 Rows = 0;
    FWriters* Writers = nullptr;
    FCounts* Counts = nullptr;
};

static void EmitReference(FReferenceContext& Context, const FString& PropertyPath, const FString& ReferenceKind, const FString& TargetPath, const FString& TargetClass)
{
    if (!Context.Writers || !Context.Counts || TargetPath.IsEmpty() || Context.Rows >= MaxReferencesPerOwner)
    {
        return;
    }
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), Context.AssetPath);
    Row->SetStringField(TEXT("owner_path"), Context.OwnerPath);
    Row->SetStringField(TEXT("owner_kind"), Context.OwnerKind);
    Row->SetStringField(TEXT("root_property"), Context.RootProperty);
    Row->SetStringField(TEXT("property_path"), PropertyPath);
    Row->SetStringField(TEXT("reference_kind"), ReferenceKind);
    Row->SetStringField(TEXT("target_path"), TargetPath);
    Row->SetStringField(TEXT("target_class"), TargetClass);
    if (Context.Writers->References.Write(Row))
    {
        ++Context.Rows;
        ++Context.Counts->References;
    }
}

static void CollectReferences(const FProperty* Property, const void* ValuePtr, const FString& PropertyPath, int32 Depth, FReferenceContext& Context)
{
    if (!Property || !ValuePtr || Depth > MaxReferenceDepth || Context.Rows >= MaxReferencesPerOwner)
    {
        return;
    }
    if (const FSoftObjectProperty* SoftProperty = CastField<FSoftObjectProperty>(Property))
    {
        const FSoftObjectPtr* SoftPtr = static_cast<const FSoftObjectPtr*>(ValuePtr);
        if (SoftPtr && !SoftPtr->IsNull())
        {
            EmitReference(Context, PropertyPath, TEXT("soft_object"), SoftPtr->ToSoftObjectPath().ToString(), FString());
        }
        return;
    }
    if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
    {
        UObject* Target = ObjectProperty->GetObjectPropertyValue(ValuePtr);
        if (Target)
        {
            EmitReference(Context, PropertyPath, TEXT("hard_object"), Target->GetPathName(), Target->GetClass()->GetPathName());
        }
        return;
    }
    if (const FStructProperty* StructProperty = CastField<FStructProperty>(Property))
    {
        if (!StructProperty->Struct)
        {
            return;
        }
        for (TFieldIterator<FProperty> It(StructProperty->Struct); It; ++It)
        {
            const FProperty* Inner = *It;
            if (!ShouldInspectProperty(Inner))
            {
                continue;
            }
            for (int32 StaticIndex = 0; StaticIndex < Inner->ArrayDim; ++StaticIndex)
            {
                const void* InnerValue = Inner->ContainerPtrToValuePtr<void>(ValuePtr, StaticIndex);
                const FString Child = PropertyPath + TEXT(".") + Inner->GetName() +
                    (Inner->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
                CollectReferences(Inner, InnerValue, Child, Depth + 1, Context);
            }
        }
        return;
    }
    if (const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
    {
        FScriptArrayHelper Helper(ArrayProperty, ValuePtr);
        const int32 Limit = FMath::Min(Helper.Num(), 4096);
        for (int32 Index = 0; Index < Limit; ++Index)
        {
            CollectReferences(ArrayProperty->Inner, Helper.GetRawPtr(Index), FString::Printf(TEXT("%s[%d]"), *PropertyPath, Index), Depth + 1, Context);
        }
        return;
    }
    if (const FSetProperty* SetProperty = CastField<FSetProperty>(Property))
    {
        FScriptSetHelper Helper(SetProperty, ValuePtr);
        int32 Emitted = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && Emitted < 4096; ++Index)
        {
            if (!Helper.IsValidIndex(Index))
            {
                continue;
            }
            CollectReferences(SetProperty->ElementProp, Helper.GetElementPtr(Index), FString::Printf(TEXT("%s{%d}"), *PropertyPath, Emitted++), Depth + 1, Context);
        }
        return;
    }
    if (const FMapProperty* MapProperty = CastField<FMapProperty>(Property))
    {
        FScriptMapHelper Helper(MapProperty, ValuePtr);
        int32 Emitted = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && Emitted < 4096; ++Index)
        {
            if (!Helper.IsValidIndex(Index))
            {
                continue;
            }
            const FString Base = FString::Printf(TEXT("%s{%d}"), *PropertyPath, Emitted++);
            CollectReferences(MapProperty->KeyProp, Helper.GetKeyPtr(Index), Base + TEXT(".key"), Depth + 1, Context);
            CollectReferences(MapProperty->ValueProp, Helper.GetValuePtr(Index), Base + TEXT(".value"), Depth + 1, Context);
        }
    }
}

static void WriteReferences(UObject* Object, const FString& AssetPath, const FString& OwnerKind, FWriters& Writers, FCounts& Counts)
{
    if (!Object)
    {
        return;
    }
    for (UClass* Class = Object->GetClass(); Class && Class != UObject::StaticClass(); Class = Class->GetSuperClass())
    {
        for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
        {
            FProperty* Property = *It;
            if (!ShouldInspectProperty(Property))
            {
                continue;
            }
            FReferenceContext Context;
            Context.AssetPath = AssetPath;
            Context.OwnerPath = Object->GetPathName();
            Context.OwnerKind = OwnerKind;
            Context.RootProperty = Property->GetName();
            Context.Writers = &Writers;
            Context.Counts = &Counts;
            for (int32 StaticIndex = 0; StaticIndex < Property->ArrayDim; ++StaticIndex)
            {
                const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object, StaticIndex);
                const FString Path = Property->GetName() +
                    (Property->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
                CollectReferences(Property, ValuePtr, Path, 0, Context);
            }
        }
    }
}

static FString KindForClass(const FString& ClassPath)
{
    if (ClassPath == TEXT("/Script/Niagara.NiagaraSystem")) return TEXT("niagara_system");
    if (ClassPath == TEXT("/Script/Niagara.NiagaraEmitter")) return TEXT("niagara_emitter");
    if (ClassPath == TEXT("/Script/Niagara.NiagaraStatelessEmitter")) return TEXT("niagara_stateless_emitter");
    if (ClassPath == TEXT("/Script/Niagara.NiagaraScript")) return TEXT("niagara_script");
    if (ClassPath == TEXT("/Script/Niagara.NiagaraDataChannelAsset")) return TEXT("niagara_data_channel");
    if (ClassPath == TEXT("/Script/Niagara.NiagaraEffectType")) return TEXT("niagara_effect_type");
    if (ClassPath == TEXT("/Script/Engine.ParticleSystem")) return TEXT("cascade_particle_system");
    return FString();
}

static bool WriteObjectState(UObject* Object, const FString& AssetPath, const FString& OwnerKind, FWriters& Writers, FCounts& Counts, TSet<FString>& SeenStateOwners)
{
    if (!Object)
    {
        return true;
    }
    const FString Path = Object->GetPathName();
    if (SeenStateOwners.Contains(Path))
    {
        return true;
    }
    SeenStateOwners.Add(Path);
    if (!WriteProperties(Object, AssetPath, OwnerKind, Writers, Counts))
    {
        return false;
    }
    WriteReferences(Object, AssetPath, OwnerKind, Writers, Counts);
    return true;
}

static bool WriteNiagaraEmitterObject(UObject* Emitter, const FString& AssetPath, FWriters& Writers, FCounts& Counts, TSet<FString>& SeenEmitters, TSet<FString>& SeenStateOwners)
{
    if (!Emitter)
    {
        return true;
    }
    const FString EmitterPath = Emitter->GetPathName();
    if (SeenEmitters.Contains(EmitterPath))
    {
        return true;
    }
    SeenEmitters.Add(EmitterPath);

    FArrayProperty* VersionData = CastField<FArrayProperty>(Emitter->GetClass()->FindPropertyByName(TEXT("VersionData")));
    const FStructProperty* VersionStruct = VersionData ? CastField<FStructProperty>(VersionData->Inner) : nullptr;
    const void* VersionArrayValue = VersionData ? VersionData->ContainerPtrToValuePtr<void>(Emitter) : nullptr;
    int32 VersionCount = 0;
    if (VersionData && VersionStruct && VersionArrayValue)
    {
        FScriptArrayHelper Versions(VersionData, VersionArrayValue);
        VersionCount = Versions.Num();
        for (int32 VersionIndex = 0; VersionIndex < Versions.Num(); ++VersionIndex)
        {
            const void* VersionValue = Versions.GetRawPtr(VersionIndex);
            const FString VersionRaw = ExportField(VersionStruct->Struct, VersionValue, TEXT("Version"), Emitter);
            const FString SimTarget = ExportField(VersionStruct->Struct, VersionValue, TEXT("SimTarget"), Emitter);
            const FString CalculateBoundsMode = ExportField(VersionStruct->Struct, VersionValue, TEXT("CalculateBoundsMode"), Emitter);
            bool bDeterminismFound = false;
            bool bLocalSpaceFound = false;
            const bool bDeterminism = GetBoolField(VersionStruct->Struct, VersionValue, TEXT("bDeterminism"), bDeterminismFound);
            const bool bLocalSpace = GetBoolField(VersionStruct->Struct, VersionValue, TEXT("bLocalSpace"), bLocalSpaceFound);
            const int32 RendererCount = CountArray(VersionStruct->Struct, VersionValue, TEXT("RendererProperties"));
            const int32 SimulationStageCount = CountArray(VersionStruct->Struct, VersionValue, TEXT("SimulationStages"));
            const int32 EventHandlerCount = CountArray(VersionStruct->Struct, VersionValue, TEXT("EventHandlerScriptProps"));

            bool bVersionTruncated = false;
            TSharedRef<FJsonObject> VersionRow = MakeShared<FJsonObject>();
            VersionRow->SetStringField(TEXT("asset_path"), AssetPath);
            VersionRow->SetStringField(TEXT("emitter_path"), EmitterPath);
            VersionRow->SetNumberField(TEXT("version_index"), VersionIndex);
            VersionRow->SetStringField(TEXT("version"), VersionRaw);
            VersionRow->SetStringField(TEXT("sim_target"), SimTarget);
            VersionRow->SetStringField(TEXT("calculate_bounds_mode"), CalculateBoundsMode);
            if (bDeterminismFound) VersionRow->SetBoolField(TEXT("determinism"), bDeterminism); else VersionRow->SetField(TEXT("determinism"), MakeShared<FJsonValueNull>());
            if (bLocalSpaceFound) VersionRow->SetBoolField(TEXT("local_space"), bLocalSpace); else VersionRow->SetField(TEXT("local_space"), MakeShared<FJsonValueNull>());
            VersionRow->SetNumberField(TEXT("renderer_count"), RendererCount);
            VersionRow->SetNumberField(TEXT("simulation_stage_count"), SimulationStageCount);
            VersionRow->SetNumberField(TEXT("event_handler_count"), EventHandlerCount);
            VersionRow->SetStringField(TEXT("raw_value"), ExportProperty(VersionData->Inner, VersionValue, Emitter, bVersionTruncated));
            VersionRow->SetBoolField(TEXT("truncated"), bVersionTruncated);
            if (!Writers.NiagaraEmitterVersions.Write(VersionRow)) return false;
            ++Counts.NiagaraEmitterVersions;

            if (FArrayProperty* Renderers = CastField<FArrayProperty>(VersionStruct->Struct->FindPropertyByName(TEXT("RendererProperties"))))
            {
                const FObjectPropertyBase* Inner = CastField<FObjectPropertyBase>(Renderers->Inner);
                const void* ValuePtr = Renderers->ContainerPtrToValuePtr<void>(VersionValue);
                if (Inner && ValuePtr)
                {
                    FScriptArrayHelper Helper(Renderers, ValuePtr);
                    for (int32 RendererIndex = 0; RendererIndex < Helper.Num(); ++RendererIndex)
                    {
                        UObject* Renderer = Inner->GetObjectPropertyValue(Helper.GetRawPtr(RendererIndex));
                        if (!Renderer) continue;
                        bool bEnabledFound = false;
                        const bool bEnabled = GetBoolField(Renderer->GetClass(), Renderer, TEXT("bIsEnabled"), bEnabledFound);
                        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
                        Row->SetStringField(TEXT("asset_path"), AssetPath);
                        Row->SetStringField(TEXT("emitter_path"), EmitterPath);
                        Row->SetNumberField(TEXT("version_index"), VersionIndex);
                        Row->SetNumberField(TEXT("renderer_index"), RendererIndex);
                        Row->SetStringField(TEXT("renderer_path"), Renderer->GetPathName());
                        Row->SetStringField(TEXT("renderer_class"), Renderer->GetClass()->GetPathName());
                        if (bEnabledFound) Row->SetBoolField(TEXT("enabled"), bEnabled); else Row->SetField(TEXT("enabled"), MakeShared<FJsonValueNull>());
                        Row->SetStringField(TEXT("sort_order_hint"), ExportField(Renderer, TEXT("SortOrderHint")));
                        if (!Writers.NiagaraRenderers.Write(Row)) return false;
                        ++Counts.NiagaraRenderers;
                        if (!WriteObjectState(Renderer, AssetPath, TEXT("niagara_renderer"), Writers, Counts, SeenStateOwners)) return false;
                    }
                }
            }

            if (FArrayProperty* Stages = CastField<FArrayProperty>(VersionStruct->Struct->FindPropertyByName(TEXT("SimulationStages"))))
            {
                const FObjectPropertyBase* Inner = CastField<FObjectPropertyBase>(Stages->Inner);
                const void* ValuePtr = Stages->ContainerPtrToValuePtr<void>(VersionValue);
                if (Inner && ValuePtr)
                {
                    FScriptArrayHelper Helper(Stages, ValuePtr);
                    for (int32 StageIndex = 0; StageIndex < Helper.Num(); ++StageIndex)
                    {
                        UObject* Stage = Inner->GetObjectPropertyValue(Helper.GetRawPtr(StageIndex));
                        if (!Stage) continue;
                        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
                        Row->SetStringField(TEXT("asset_path"), AssetPath);
                        Row->SetStringField(TEXT("emitter_path"), EmitterPath);
                        Row->SetNumberField(TEXT("version_index"), VersionIndex);
                        Row->SetNumberField(TEXT("stage_index"), StageIndex);
                        Row->SetStringField(TEXT("stage_path"), Stage->GetPathName());
                        Row->SetStringField(TEXT("stage_class"), Stage->GetClass()->GetPathName());
                        Row->SetStringField(TEXT("script_usage_id"), ExportField(Stage, TEXT("ScriptUsageId")));
                        Row->SetStringField(TEXT("iteration_source"), ExportField(Stage, TEXT("IterationSource")));
                        if (!Writers.NiagaraSimulationStages.Write(Row)) return false;
                        ++Counts.NiagaraSimulationStages;
                        if (!WriteObjectState(Stage, AssetPath, TEXT("niagara_simulation_stage"), Writers, Counts, SeenStateOwners)) return false;
                    }
                }
            }
        }
    }

    bool bVersioningFound = false;
    const bool bVersioning = GetBoolField(Emitter->GetClass(), Emitter, TEXT("bVersioningEnabled"), bVersioningFound);
    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("asset_path"), AssetPath);
    Summary->SetStringField(TEXT("emitter_path"), EmitterPath);
    Summary->SetStringField(TEXT("class_path"), Emitter->GetClass()->GetPathName());
    Summary->SetNumberField(TEXT("version_count"), VersionCount);
    Summary->SetStringField(TEXT("exposed_version"), ExportField(Emitter, TEXT("ExposedVersion")));
    if (bVersioningFound) Summary->SetBoolField(TEXT("versioning_enabled"), bVersioning); else Summary->SetField(TEXT("versioning_enabled"), MakeShared<FJsonValueNull>());
    if (!Writers.NiagaraEmitters.Write(Summary)) return false;
    ++Counts.NiagaraEmitters;
    return WriteObjectState(Emitter, AssetPath, TEXT("niagara_emitter"), Writers, Counts, SeenStateOwners);
}

static bool ScanNiagaraSystem(UObject* Object, const FAssetData& Asset, FWriters& Writers, FCounts& Counts, TSet<FString>& SeenEmitters, TSet<FString>& SeenStateOwners)
{
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    FArrayProperty* Handles = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(TEXT("EmitterHandles")));
    const FStructProperty* HandleStruct = Handles ? CastField<FStructProperty>(Handles->Inner) : nullptr;
    const void* ArrayValue = Handles ? Handles->ContainerPtrToValuePtr<void>(Object) : nullptr;
    int32 HandleCount = 0;
    if (Handles && HandleStruct && ArrayValue)
    {
        FScriptArrayHelper Helper(Handles, ArrayValue);
        HandleCount = Helper.Num();
        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            const void* Handle = Helper.GetRawPtr(Index);
            UObject* StatelessEmitter = GetObjectField(HandleStruct->Struct, Handle, TEXT("StatelessEmitter"));
            UObject* Emitter = nullptr;
            FString Version;
            if (const FStructProperty* Versioned = CastField<FStructProperty>(HandleStruct->Struct->FindPropertyByName(TEXT("VersionedInstance"))))
            {
                const void* VersionedValue = Versioned->ContainerPtrToValuePtr<void>(Handle);
                Emitter = GetObjectField(Versioned->Struct, VersionedValue, TEXT("Emitter"));
                Version = ExportField(Versioned->Struct, VersionedValue, TEXT("Version"), Object);
            }
            bool bEnabledFound = false;
            const bool bEnabled = GetBoolField(HandleStruct->Struct, Handle, TEXT("bIsEnabled"), bEnabledFound);
            bool bTruncated = false;
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("system_path"), AssetPath);
            Row->SetNumberField(TEXT("emitter_index"), Index);
            Row->SetStringField(TEXT("name"), GetNameField(HandleStruct->Struct, Handle, TEXT("Name"), Object));
            Row->SetStringField(TEXT("id"), ExportField(HandleStruct->Struct, Handle, TEXT("Id"), Object));
            Row->SetStringField(TEXT("id_name"), GetNameField(HandleStruct->Struct, Handle, TEXT("IdName"), Object));
            if (bEnabledFound) Row->SetBoolField(TEXT("enabled"), bEnabled); else Row->SetField(TEXT("enabled"), MakeShared<FJsonValueNull>());
            Row->SetStringField(TEXT("emitter_mode"), ExportField(HandleStruct->Struct, Handle, TEXT("EmitterMode"), Object));
            Row->SetStringField(TEXT("emitter_path"), Emitter ? Emitter->GetPathName() : FString());
            Row->SetStringField(TEXT("emitter_class"), Emitter ? Emitter->GetClass()->GetPathName() : FString());
            Row->SetStringField(TEXT("emitter_version"), Version);
            Row->SetStringField(TEXT("stateless_emitter_path"), StatelessEmitter ? StatelessEmitter->GetPathName() : FString());
            Row->SetStringField(TEXT("stateless_emitter_class"), StatelessEmitter ? StatelessEmitter->GetClass()->GetPathName() : FString());
            Row->SetStringField(TEXT("raw_value"), ExportProperty(Handles->Inner, Handle, Object, bTruncated));
            Row->SetBoolField(TEXT("truncated"), bTruncated);
            if (!Writers.NiagaraSystemEmitters.Write(Row)) return false;
            ++Counts.NiagaraSystemEmitters;
            if (Emitter && !WriteNiagaraEmitterObject(Emitter, AssetPath, Writers, Counts, SeenEmitters, SeenStateOwners)) return false;
            if (StatelessEmitter && !WriteObjectState(StatelessEmitter, AssetPath, TEXT("niagara_stateless_emitter"), Writers, Counts, SeenStateOwners)) return false;
        }
    }

    UObject* EffectType = GetObjectField(Object, TEXT("EffectType"));
    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("system_path"), AssetPath);
    Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetNumberField(TEXT("emitter_count"), HandleCount);
    Summary->SetStringField(TEXT("effect_type_path"), EffectType ? EffectType->GetPathName() : FString());
    Summary->SetStringField(TEXT("warmup_time"), ExportField(Object, TEXT("WarmupTime")));
    Summary->SetStringField(TEXT("warmup_tick_delta"), ExportField(Object, TEXT("WarmupTickDelta")));
    Summary->SetStringField(TEXT("fixed_bounds"), ExportField(Object, TEXT("FixedBounds")));
    if (!Writers.NiagaraSystems.Write(Summary)) return false;
    ++Counts.NiagaraSystems;
    return true;
}

static bool ScanNiagaraScript(UObject* Object, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("script_path"), Asset.GetSoftObjectPath().ToString());
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("usage"), ExportField(Object, TEXT("Usage")));
    Row->SetStringField(TEXT("usage_id"), ExportField(Object, TEXT("UsageId")));
    Row->SetStringField(TEXT("exposed_version"), ExportField(Object, TEXT("ExposedVersion")));
    Row->SetNumberField(TEXT("version_count"), CountArray(Object->GetClass(), Object, TEXT("VersionData")));
    if (!Writers.NiagaraScripts.Write(Row)) return false;
    ++Counts.NiagaraScripts;
    return true;
}

static bool ScanNiagaraDataChannel(UObject* Object, const FAssetData& Asset, FWriters& Writers, FCounts& Counts, TSet<FString>& SeenStateOwners)
{
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    UObject* DataChannel = GetObjectField(Object, TEXT("DataChannel"));
    int32 VariableCount = 0;
    if (DataChannel)
    {
        FArrayProperty* Variables = CastField<FArrayProperty>(DataChannel->GetClass()->FindPropertyByName(TEXT("Variables")));
        const FStructProperty* VariableStruct = Variables ? CastField<FStructProperty>(Variables->Inner) : nullptr;
        const void* ValuePtr = Variables ? Variables->ContainerPtrToValuePtr<void>(DataChannel) : nullptr;
        if (Variables && VariableStruct && ValuePtr)
        {
            FScriptArrayHelper Helper(Variables, ValuePtr);
            VariableCount = Helper.Num();
            for (int32 Index = 0; Index < Helper.Num(); ++Index)
            {
                const void* Variable = Helper.GetRawPtr(Index);
                bool bTruncated = false;
                TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
                Row->SetStringField(TEXT("data_channel_path"), AssetPath);
                Row->SetNumberField(TEXT("variable_index"), Index);
                Row->SetStringField(TEXT("name"), GetNameField(VariableStruct->Struct, Variable, TEXT("Name"), DataChannel));
                Row->SetStringField(TEXT("type"), ExportField(VariableStruct->Struct, Variable, TEXT("TypeDef"), DataChannel));
                Row->SetStringField(TEXT("raw_value"), ExportProperty(Variables->Inner, Variable, DataChannel, bTruncated));
                Row->SetBoolField(TEXT("truncated"), bTruncated);
                if (!Writers.NiagaraDataChannelVariables.Write(Row)) return false;
                ++Counts.NiagaraDataChannelVariables;
            }
        }
        if (!WriteObjectState(DataChannel, AssetPath, TEXT("niagara_data_channel_definition"), Writers, Counts, SeenStateOwners)) return false;
    }
    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("data_channel_path"), AssetPath);
    Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetStringField(TEXT("definition_path"), DataChannel ? DataChannel->GetPathName() : FString());
    Summary->SetStringField(TEXT("definition_class"), DataChannel ? DataChannel->GetClass()->GetPathName() : FString());
    Summary->SetNumberField(TEXT("variable_count"), VariableCount);
    if (!Writers.NiagaraDataChannels.Write(Summary)) return false;
    ++Counts.NiagaraDataChannels;
    return true;
}

static bool ScanCascadeSystem(UObject* Object, const FAssetData& Asset, FWriters& Writers, FCounts& Counts, TSet<FString>& SeenStateOwners)
{
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    FArrayProperty* Emitters = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(TEXT("Emitters")));
    const FObjectPropertyBase* EmitterInner = Emitters ? CastField<FObjectPropertyBase>(Emitters->Inner) : nullptr;
    const void* EmittersValue = Emitters ? Emitters->ContainerPtrToValuePtr<void>(Object) : nullptr;
    int32 EmitterCount = 0;
    if (Emitters && EmitterInner && EmittersValue)
    {
        FScriptArrayHelper EmitterHelper(Emitters, EmittersValue);
        EmitterCount = EmitterHelper.Num();
        for (int32 EmitterIndex = 0; EmitterIndex < EmitterHelper.Num(); ++EmitterIndex)
        {
            UObject* Emitter = EmitterInner->GetObjectPropertyValue(EmitterHelper.GetRawPtr(EmitterIndex));
            if (!Emitter) continue;
            FArrayProperty* LODLevels = CastField<FArrayProperty>(Emitter->GetClass()->FindPropertyByName(TEXT("LODLevels")));
            const FObjectPropertyBase* LODInner = LODLevels ? CastField<FObjectPropertyBase>(LODLevels->Inner) : nullptr;
            const void* LODValue = LODLevels ? LODLevels->ContainerPtrToValuePtr<void>(Emitter) : nullptr;
            const int32 LODCount = LODLevels && LODValue ? FScriptArrayHelper(LODLevels, LODValue).Num() : 0;
            TSharedRef<FJsonObject> EmitterRow = MakeShared<FJsonObject>();
            EmitterRow->SetStringField(TEXT("system_path"), AssetPath);
            EmitterRow->SetNumberField(TEXT("emitter_index"), EmitterIndex);
            EmitterRow->SetStringField(TEXT("emitter_path"), Emitter->GetPathName());
            EmitterRow->SetStringField(TEXT("emitter_class"), Emitter->GetClass()->GetPathName());
            EmitterRow->SetStringField(TEXT("emitter_name"), GetNameField(Emitter->GetClass(), Emitter, TEXT("EmitterName"), Emitter));
            EmitterRow->SetNumberField(TEXT("lod_count"), LODCount);
            EmitterRow->SetStringField(TEXT("significance_level"), ExportField(Emitter, TEXT("SignificanceLevel")));
            if (!Writers.CascadeEmitters.Write(EmitterRow)) return false;
            ++Counts.CascadeEmitters;
            if (!WriteObjectState(Emitter, AssetPath, TEXT("cascade_emitter"), Writers, Counts, SeenStateOwners)) return false;

            if (LODLevels && LODInner && LODValue)
            {
                FScriptArrayHelper LODHelper(LODLevels, LODValue);
                for (int32 LODIndex = 0; LODIndex < LODHelper.Num(); ++LODIndex)
                {
                    UObject* LOD = LODInner->GetObjectPropertyValue(LODHelper.GetRawPtr(LODIndex));
                    if (!LOD) continue;
                    bool bEnabledFound = false;
                    const bool bEnabled = GetBoolField(LOD->GetClass(), LOD, TEXT("bEnabled"), bEnabledFound);
                    const int32 ModuleArrayCount = CountArray(LOD->GetClass(), LOD, TEXT("Modules"));
                    TSharedRef<FJsonObject> LODRow = MakeShared<FJsonObject>();
                    LODRow->SetStringField(TEXT("system_path"), AssetPath);
                    LODRow->SetNumberField(TEXT("emitter_index"), EmitterIndex);
                    LODRow->SetNumberField(TEXT("lod_index"), LODIndex);
                    LODRow->SetStringField(TEXT("lod_path"), LOD->GetPathName());
                    LODRow->SetStringField(TEXT("level"), ExportField(LOD, TEXT("Level")));
                    if (bEnabledFound) LODRow->SetBoolField(TEXT("enabled"), bEnabled); else LODRow->SetField(TEXT("enabled"), MakeShared<FJsonValueNull>());
                    LODRow->SetNumberField(TEXT("module_array_count"), ModuleArrayCount);
                    if (!Writers.CascadeLODs.Write(LODRow)) return false;
                    ++Counts.CascadeLODs;
                    if (!WriteObjectState(LOD, AssetPath, TEXT("cascade_lod"), Writers, Counts, SeenStateOwners)) return false;

                    TSet<FString> SeenModules;
                    int32 ModuleIndex = 0;
                    const auto EmitModule = [&](UObject* Module, const FString& Role) -> bool
                    {
                        if (!Module) return true;
                        const FString ModulePath = Module->GetPathName();
                        const FString DedupKey = Role + TEXT("|") + ModulePath;
                        if (SeenModules.Contains(DedupKey)) return true;
                        SeenModules.Add(DedupKey);
                        TSharedRef<FJsonObject> ModuleRow = MakeShared<FJsonObject>();
                        ModuleRow->SetStringField(TEXT("system_path"), AssetPath);
                        ModuleRow->SetNumberField(TEXT("emitter_index"), EmitterIndex);
                        ModuleRow->SetNumberField(TEXT("lod_index"), LODIndex);
                        ModuleRow->SetNumberField(TEXT("module_index"), ModuleIndex++);
                        ModuleRow->SetStringField(TEXT("role"), Role);
                        ModuleRow->SetStringField(TEXT("module_path"), ModulePath);
                        ModuleRow->SetStringField(TEXT("module_class"), Module->GetClass()->GetPathName());
                        if (!Writers.CascadeModules.Write(ModuleRow)) return false;
                        ++Counts.CascadeModules;
                        return WriteObjectState(Module, AssetPath, TEXT("cascade_module"), Writers, Counts, SeenStateOwners);
                    };

                    if (!EmitModule(GetObjectField(LOD, TEXT("RequiredModule")), TEXT("required"))) return false;
                    if (!EmitModule(GetObjectField(LOD, TEXT("SpawnModule")), TEXT("spawn"))) return false;
                    if (!EmitModule(GetObjectField(LOD, TEXT("TypeDataModule")), TEXT("type_data"))) return false;
                    if (FArrayProperty* Modules = CastField<FArrayProperty>(LOD->GetClass()->FindPropertyByName(TEXT("Modules"))))
                    {
                        const FObjectPropertyBase* Inner = CastField<FObjectPropertyBase>(Modules->Inner);
                        const void* ValuePtr = Modules->ContainerPtrToValuePtr<void>(LOD);
                        if (Inner && ValuePtr)
                        {
                            FScriptArrayHelper Helper(Modules, ValuePtr);
                            for (int32 Index = 0; Index < Helper.Num(); ++Index)
                            {
                                if (!EmitModule(Inner->GetObjectPropertyValue(Helper.GetRawPtr(Index)), TEXT("module"))) return false;
                            }
                        }
                    }
                }
            }
        }
    }
    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("system_path"), AssetPath);
    Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetNumberField(TEXT("emitter_count"), EmitterCount);
    Summary->SetStringField(TEXT("warmup_time"), ExportField(Object, TEXT("WarmupTime")));
    Summary->SetStringField(TEXT("delay"), ExportField(Object, TEXT("Delay")));
    Summary->SetStringField(TEXT("lod_method"), ExportField(Object, TEXT("LODMethod")));
    if (!Writers.CascadeSystems.Write(Summary)) return false;
    ++Counts.CascadeSystems;
    return true;
}

static bool SaveManifest(const FString& OutputDir, const FCounts& Counts, bool bSuccess, const FString& Error)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetNumberField(TEXT("schema_version"), VFXSchemaVersion);
    Root->SetStringField(TEXT("pass"), TEXT("UnrealAssetToolVFX"));
    Root->SetStringField(TEXT("generated_utc"), FDateTime::UtcNow().ToIso8601());
    Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetBoolField(TEXT("success"), bSuccess);
    Root->SetStringField(TEXT("error"), Error);
    TSharedRef<FJsonObject> C = MakeShared<FJsonObject>();
    C->SetNumberField(TEXT("vfx_assets"), Counts.Assets);
    C->SetNumberField(TEXT("vfx_properties"), Counts.Properties);
    C->SetNumberField(TEXT("vfx_references"), Counts.References);
    C->SetNumberField(TEXT("niagara_systems"), Counts.NiagaraSystems);
    C->SetNumberField(TEXT("niagara_system_emitters"), Counts.NiagaraSystemEmitters);
    C->SetNumberField(TEXT("niagara_emitters"), Counts.NiagaraEmitters);
    C->SetNumberField(TEXT("niagara_emitter_versions"), Counts.NiagaraEmitterVersions);
    C->SetNumberField(TEXT("niagara_renderers"), Counts.NiagaraRenderers);
    C->SetNumberField(TEXT("niagara_simulation_stages"), Counts.NiagaraSimulationStages);
    C->SetNumberField(TEXT("niagara_scripts"), Counts.NiagaraScripts);
    C->SetNumberField(TEXT("niagara_data_channels"), Counts.NiagaraDataChannels);
    C->SetNumberField(TEXT("niagara_data_channel_variables"), Counts.NiagaraDataChannelVariables);
    C->SetNumberField(TEXT("niagara_effect_types"), Counts.NiagaraEffectTypes);
    C->SetNumberField(TEXT("cascade_systems"), Counts.CascadeSystems);
    C->SetNumberField(TEXT("cascade_emitters"), Counts.CascadeEmitters);
    C->SetNumberField(TEXT("cascade_lods"), Counts.CascadeLODs);
    C->SetNumberField(TEXT("cascade_modules"), Counts.CascadeModules);
    Root->SetObjectField(TEXT("counts"), C);

    static const TCHAR* Names[] = {
        TEXT("vfx_assets.jsonl"), TEXT("vfx_properties.jsonl"), TEXT("vfx_references.jsonl"),
        TEXT("niagara_systems.jsonl"), TEXT("niagara_system_emitters.jsonl"), TEXT("niagara_emitters.jsonl"),
        TEXT("niagara_emitter_versions.jsonl"), TEXT("niagara_renderers.jsonl"), TEXT("niagara_simulation_stages.jsonl"),
        TEXT("niagara_scripts.jsonl"), TEXT("niagara_data_channels.jsonl"), TEXT("niagara_data_channel_variables.jsonl"),
        TEXT("niagara_effect_types.jsonl"), TEXT("cascade_systems.jsonl"), TEXT("cascade_emitters.jsonl"),
        TEXT("cascade_lods.jsonl"), TEXT("cascade_modules.jsonl")
    };
    TArray<TSharedPtr<FJsonValue>> Files;
    for (const TCHAR* Name : Names)
    {
        Files.Add(MakeShared<FJsonValueString>(Name));
    }
    Root->SetArrayField(TEXT("files"), Files);

    FString Text;
    const TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer =
        TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Text);
    if (!FJsonSerializer::Serialize(Root, Writer))
    {
        return false;
    }
    return FFileHelper::SaveStringToFile(Text, *FPaths::Combine(OutputDir, TEXT("vfx_manifest.json")), FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

static bool RunVFXScan(FString& OutError)
{
    FString OutputDir;
    FParse::Value(FCommandLine::Get(), TEXT("Output="), OutputDir);
    const FString ProjectDir = NormalizeAbsolutePath(FPaths::ProjectDir());
    if (OutputDir.IsEmpty()) OutputDir = FPaths::Combine(ProjectDir, TEXT(".uatool"));
    else if (FPaths::IsRelative(OutputDir)) OutputDir = FPaths::Combine(ProjectDir, OutputDir);
    OutputDir = NormalizeAbsolutePath(OutputDir);
    IFileManager::Get().MakeDirectory(*OutputDir, true);

    const bool bIncludeEngine = FParse::Param(FCommandLine::Get(), TEXT("IncludeEngine"));
    const bool bIncludeSelf = FParse::Param(FCommandLine::Get(), TEXT("IncludeSelf"));
    FString ToolPluginDir;
    if (const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("UnrealAssetTool")); Plugin.IsValid())
    {
        ToolPluginDir = NormalizeAbsolutePath(Plugin->GetBaseDir());
    }

    FWriters Writers;
    FCounts Counts;
    if (!Writers.Open(OutputDir))
    {
        OutError = TEXT("could not create VFX JSONL output files");
        SaveManifest(OutputDir, Counts, false, OutError);
        return false;
    }

    FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
    IAssetRegistry& Registry = AssetRegistryModule.Get();
    Registry.SearchAllAssets(true);
    TArray<FAssetData> Assets;
    Registry.GetAllAssets(Assets, true);
    Assets.Sort([](const FAssetData& A, const FAssetData& B) { return A.GetSoftObjectPath().ToString() < B.GetSoftObjectPath().ToString(); });

    TSet<FString> SeenNiagaraEmitters;
    TSet<FString> SeenStateOwners;
    for (const FAssetData& Asset : Assets)
    {
        const FString Kind = KindForClass(Asset.AssetClassPath.ToString());
        if (Kind.IsEmpty()) continue;
        FString PackageFilename;
        const bool bHasDiskPackage = FPackageName::DoesPackageExist(Asset.PackageName.ToString(), &PackageFilename, false);
        if (!bIncludeSelf && bHasDiskPackage && !ToolPluginDir.IsEmpty() && IsInsideDirectory(PackageFilename, ToolPluginDir)) continue;
        if (!bIncludeEngine && (!bHasDiskPackage || !IsInsideDirectory(PackageFilename, ProjectDir))) continue;

        UObject* Object = Asset.GetAsset();
        if (!Object) continue;
        const FString AssetPath = Asset.GetSoftObjectPath().ToString();
        TSharedRef<FJsonObject> AssetRow = MakeShared<FJsonObject>();
        AssetRow->SetStringField(TEXT("vfx_path"), AssetPath);
        AssetRow->SetStringField(TEXT("vfx_kind"), Kind);
        AssetRow->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
        AssetRow->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
        AssetRow->SetStringField(TEXT("family"), Kind.StartsWith(TEXT("niagara_")) ? TEXT("niagara") : TEXT("cascade"));
        if (!Writers.Assets.Write(AssetRow))
        {
            OutError = TEXT("failed writing VFX asset ") + AssetPath;
            SaveManifest(OutputDir, Counts, false, OutError);
            return false;
        }
        ++Counts.Assets;
        if (!WriteObjectState(Object, AssetPath, Kind, Writers, Counts, SeenStateOwners))
        {
            OutError = TEXT("failed writing VFX state for ") + AssetPath;
            SaveManifest(OutputDir, Counts, false, OutError);
            return false;
        }

        bool bOk = true;
        if (Kind == TEXT("niagara_system")) bOk = ScanNiagaraSystem(Object, Asset, Writers, Counts, SeenNiagaraEmitters, SeenStateOwners);
        else if (Kind == TEXT("niagara_emitter")) bOk = WriteNiagaraEmitterObject(Object, AssetPath, Writers, Counts, SeenNiagaraEmitters, SeenStateOwners);
        else if (Kind == TEXT("niagara_stateless_emitter")) bOk = true;
        else if (Kind == TEXT("niagara_script")) bOk = ScanNiagaraScript(Object, Asset, Writers, Counts);
        else if (Kind == TEXT("niagara_data_channel")) bOk = ScanNiagaraDataChannel(Object, Asset, Writers, Counts, SeenStateOwners);
        else if (Kind == TEXT("niagara_effect_type"))
        {
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("effect_type_path"), AssetPath);
            Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
            Row->SetStringField(TEXT("update_frequency"), ExportField(Object, TEXT("UpdateFrequency")));
            Row->SetStringField(TEXT("cull_reaction"), ExportField(Object, TEXT("CullReaction")));
            bOk = Writers.NiagaraEffectTypes.Write(Row);
            if (bOk) ++Counts.NiagaraEffectTypes;
        }
        else if (Kind == TEXT("cascade_particle_system")) bOk = ScanCascadeSystem(Object, Asset, Writers, Counts, SeenStateOwners);

        if (!bOk)
        {
            OutError = TEXT("failed while scanning VFX asset ") + AssetPath;
            SaveManifest(OutputDir, Counts, false, OutError);
            return false;
        }
    }

    if (!SaveManifest(OutputDir, Counts, true, FString()))
    {
        OutError = TEXT("could not write vfx_manifest.json");
        return false;
    }
    UE_LOG(LogTemp, Display,
        TEXT("UnrealAssetToolVFX: assets=%lld systems=%lld system_emitters=%lld emitters=%lld renderers=%lld cascade_systems=%lld cascade_modules=%lld"),
        Counts.Assets, Counts.NiagaraSystems, Counts.NiagaraSystemEmitters, Counts.NiagaraEmitters,
        Counts.NiagaraRenderers, Counts.CascadeSystems, Counts.CascadeModules);
    return true;
}

static void OnPostEngineInit()
{
    FString RunCommandlet;
    FParse::Value(FCommandLine::Get(), TEXT("run="), RunCommandlet);
    if (!RunCommandlet.Equals(TEXT("UnrealAssetToolWorld"), ESearchCase::IgnoreCase))
    {
        return;
    }
    FString Error;
    if (!RunVFXScan(Error))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolVFX: %s"), *Error);
    }
}

struct FVFXScannerBootstrap
{
    FVFXScannerBootstrap()
    {
        FCoreDelegates::GetOnPostEngineInit().AddStatic(&OnPostEngineInit);
    }
};

static FVFXScannerBootstrap GVFXScannerBootstrap;
}

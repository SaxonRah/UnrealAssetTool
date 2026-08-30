static constexpr int32 VFXSchemaVersion = 1;
static constexpr int32 MaxExportChars = 65536;
static constexpr int32 MaxReferenceDepth = 8;
static constexpr int32 MaxReferencesPerRoot = 4096;

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

    int64 NiagaraStatelessEmitters = 0;
    int64 NiagaraStatelessModules = 0;
    int64 NiagaraStatelessRenderers = 0;

    int64 NiagaraScripts = 0;
    int64 NiagaraDataChannels = 0;
    int64 NiagaraDataChannelVariables = 0;
    int64 NiagaraParameterCollections = 0;
    int64 NiagaraParameterCollectionParameters = 0;
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

    FJsonlWriter NiagaraStatelessEmitters;
    FJsonlWriter NiagaraStatelessModules;
    FJsonlWriter NiagaraStatelessRenderers;

    FJsonlWriter NiagaraScripts;
    FJsonlWriter NiagaraDataChannels;
    FJsonlWriter NiagaraDataChannelVariables;
    FJsonlWriter NiagaraParameterCollections;
    FJsonlWriter NiagaraParameterCollectionParameters;
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
            NiagaraStatelessEmitters.Open(FPaths::Combine(OutputDir, TEXT("niagara_stateless_emitters.jsonl"))) &&
            NiagaraStatelessModules.Open(FPaths::Combine(OutputDir, TEXT("niagara_stateless_modules.jsonl"))) &&
            NiagaraStatelessRenderers.Open(FPaths::Combine(OutputDir, TEXT("niagara_stateless_renderers.jsonl"))) &&
            NiagaraScripts.Open(FPaths::Combine(OutputDir, TEXT("niagara_scripts.jsonl"))) &&
            NiagaraDataChannels.Open(FPaths::Combine(OutputDir, TEXT("niagara_data_channels.jsonl"))) &&
            NiagaraDataChannelVariables.Open(FPaths::Combine(OutputDir, TEXT("niagara_data_channel_variables.jsonl"))) &&
            NiagaraParameterCollections.Open(FPaths::Combine(OutputDir, TEXT("niagara_parameter_collections.jsonl"))) &&
            NiagaraParameterCollectionParameters.Open(FPaths::Combine(OutputDir, TEXT("niagara_parameter_collection_parameters.jsonl"))) &&
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

static FString ExportProperty(
    const FProperty* Property,
    const void* ValuePtr,
    UObject* Owner,
    bool& bTruncated)
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
    if (Value.StartsWith(TEXT("\"")) && Value.EndsWith(TEXT("\"")) && Value.Len() >= 2)
    {
        Value = Value.Mid(1, Value.Len() - 2);
    }
    return Value;
}

static bool GetBoolField(
    UStruct* Struct,
    const void* StructValue,
    const FName FieldName,
    bool& bFound)
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

static FArrayProperty* FindArrayField(UStruct* Struct, const FName First, const FName Second = NAME_None)
{
    if (!Struct)
    {
        return nullptr;
    }

    if (FArrayProperty* Array = CastField<FArrayProperty>(Struct->FindPropertyByName(First)))
    {
        return Array;
    }

    return Second.IsNone()
        ? nullptr
        : CastField<FArrayProperty>(Struct->FindPropertyByName(Second));
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

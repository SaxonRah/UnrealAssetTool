static constexpr int32 SystemsSchemaVersion = 2;
static constexpr int32 MaxExportChars = 65536;
static constexpr int32 MaxReferenceDepth = 8;
static constexpr int32 MaxReferencesPerRoot = 4096;
static constexpr int32 MaxNestedObjectsPerAsset = 8192;
static constexpr int32 MaxStructuredRowsPerAsset = 65536;

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

    int64 LevelSequences = 0;
    int64 MovieSceneBindings = 0;
    int64 MovieSceneTracks = 0;
    int64 MovieSceneSections = 0;
    int64 MovieSceneChannels = 0;

    int64 AudioAssets = 0;
    int64 SoundCueNodes = 0;
    int64 MetaSoundNodes = 0;
    int64 MetaSoundEdges = 0;

    int64 InputActions = 0;
    int64 InputMappingContexts = 0;
    int64 InputMappings = 0;
    int64 InputProcessors = 0;

    int64 GameplayDataAssets = 0;
    int64 GameplayTags = 0;

    int64 DataTableRows = 0;
    int64 DataTableFields = 0;
    int64 CurveTables = 0;
    int64 CurveTableRows = 0;
    int64 CurveTableKeys = 0;
    int64 PrimaryDataAssets = 0;
    int64 GameplayTagSettings = 0;
    int64 GameplayTagSources = 0;
    int64 GameplayTagDictionary = 0;
    int64 GameplayTagRedirects = 0;
};

struct FWriters
{
    FJsonlWriter Assets;
    FJsonlWriter Properties;
    FJsonlWriter References;

    FJsonlWriter LevelSequences;
    FJsonlWriter MovieSceneBindings;
    FJsonlWriter MovieSceneTracks;
    FJsonlWriter MovieSceneSections;
    FJsonlWriter MovieSceneChannels;

    FJsonlWriter AudioAssets;
    FJsonlWriter SoundCueNodes;
    FJsonlWriter MetaSoundNodes;
    FJsonlWriter MetaSoundEdges;

    FJsonlWriter InputActions;
    FJsonlWriter InputMappingContexts;
    FJsonlWriter InputMappings;
    FJsonlWriter InputProcessors;

    FJsonlWriter GameplayDataAssets;
    FJsonlWriter GameplayTags;

    FJsonlWriter DataTableRows;
    FJsonlWriter DataTableFields;
    FJsonlWriter CurveTables;
    FJsonlWriter CurveTableRows;
    FJsonlWriter CurveTableKeys;
    FJsonlWriter PrimaryDataAssets;
    FJsonlWriter GameplayTagSettings;
    FJsonlWriter GameplayTagSources;
    FJsonlWriter GameplayTagDictionary;
    FJsonlWriter GameplayTagRedirects;

    bool Open(const FString& OutputDir)
    {
        return Assets.Open(FPaths::Combine(OutputDir, TEXT("systems_assets.jsonl"))) &&
            Properties.Open(FPaths::Combine(OutputDir, TEXT("systems_properties.jsonl"))) &&
            References.Open(FPaths::Combine(OutputDir, TEXT("systems_references.jsonl"))) &&
            LevelSequences.Open(FPaths::Combine(OutputDir, TEXT("level_sequences.jsonl"))) &&
            MovieSceneBindings.Open(FPaths::Combine(OutputDir, TEXT("movie_scene_bindings.jsonl"))) &&
            MovieSceneTracks.Open(FPaths::Combine(OutputDir, TEXT("movie_scene_tracks.jsonl"))) &&
            MovieSceneSections.Open(FPaths::Combine(OutputDir, TEXT("movie_scene_sections.jsonl"))) &&
            MovieSceneChannels.Open(FPaths::Combine(OutputDir, TEXT("movie_scene_channels.jsonl"))) &&
            AudioAssets.Open(FPaths::Combine(OutputDir, TEXT("audio_assets.jsonl"))) &&
            SoundCueNodes.Open(FPaths::Combine(OutputDir, TEXT("sound_cue_nodes.jsonl"))) &&
            MetaSoundNodes.Open(FPaths::Combine(OutputDir, TEXT("metasound_nodes.jsonl"))) &&
            MetaSoundEdges.Open(FPaths::Combine(OutputDir, TEXT("metasound_edges.jsonl"))) &&
            InputActions.Open(FPaths::Combine(OutputDir, TEXT("input_actions.jsonl"))) &&
            InputMappingContexts.Open(FPaths::Combine(OutputDir, TEXT("input_mapping_contexts.jsonl"))) &&
            InputMappings.Open(FPaths::Combine(OutputDir, TEXT("input_mappings.jsonl"))) &&
            InputProcessors.Open(FPaths::Combine(OutputDir, TEXT("input_processors.jsonl"))) &&
            GameplayDataAssets.Open(FPaths::Combine(OutputDir, TEXT("gameplay_data_assets.jsonl"))) &&
            GameplayTags.Open(FPaths::Combine(OutputDir, TEXT("gameplay_tags.jsonl"))) &&
            DataTableRows.Open(FPaths::Combine(OutputDir, TEXT("data_table_rows.jsonl"))) &&
            DataTableFields.Open(FPaths::Combine(OutputDir, TEXT("data_table_fields.jsonl"))) &&
            CurveTables.Open(FPaths::Combine(OutputDir, TEXT("curve_tables.jsonl"))) &&
            CurveTableRows.Open(FPaths::Combine(OutputDir, TEXT("curve_table_rows.jsonl"))) &&
            CurveTableKeys.Open(FPaths::Combine(OutputDir, TEXT("curve_table_keys.jsonl"))) &&
            PrimaryDataAssets.Open(FPaths::Combine(OutputDir, TEXT("primary_data_assets.jsonl"))) &&
            GameplayTagSettings.Open(FPaths::Combine(OutputDir, TEXT("gameplay_tag_settings.jsonl"))) &&
            GameplayTagSources.Open(FPaths::Combine(OutputDir, TEXT("gameplay_tag_sources.jsonl"))) &&
            GameplayTagDictionary.Open(FPaths::Combine(OutputDir, TEXT("gameplay_tag_dictionary.jsonl"))) &&
            GameplayTagRedirects.Open(FPaths::Combine(OutputDir, TEXT("gameplay_tag_redirects.jsonl")));
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

static FString ExportField(const UStruct* Struct, const void* StructValue, const FName FieldName, UObject* Owner)
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

static FString ExportFirstField(UObject* Object, std::initializer_list<const TCHAR*> Names)
{
    if (!Object)
    {
        return FString();
    }
    for (const TCHAR* Name : Names)
    {
        const FName FieldName(Name);
        if (Object->GetClass()->FindPropertyByName(FieldName))
        {
            return ExportField(Object, FieldName);
        }
    }
    return FString();
}

static FString ExportFirstField(const UStruct* Struct, const void* Value, UObject* Owner, std::initializer_list<const TCHAR*> Names)
{
    if (!Struct || !Value)
    {
        return FString();
    }
    for (const TCHAR* Name : Names)
    {
        const FName FieldName(Name);
        if (Struct->FindPropertyByName(FieldName))
        {
            return ExportField(Struct, Value, FieldName, Owner);
        }
    }
    return FString();
}

static UObject* GetObjectField(const UStruct* Struct, const void* StructValue, const FName FieldName)
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

static UObject* GetFirstObjectField(UObject* Object, std::initializer_list<const TCHAR*> Names)
{
    if (!Object)
    {
        return nullptr;
    }
    for (const TCHAR* Name : Names)
    {
        if (UObject* Value = GetObjectField(Object, FName(Name)))
        {
            return Value;
        }
    }
    return nullptr;
}

static UObject* GetFirstObjectField(const UStruct* Struct, const void* Value, std::initializer_list<const TCHAR*> Names)
{
    if (!Struct || !Value)
    {
        return nullptr;
    }
    for (const TCHAR* Name : Names)
    {
        if (UObject* Object = GetObjectField(Struct, Value, FName(Name)))
        {
            return Object;
        }
    }
    return nullptr;
}

static FString GetNameField(const UStruct* Struct, const void* StructValue, const FName FieldName, UObject* Owner)
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

static int32 GetArrayCount(const UStruct* Struct, const void* StructValue, const FName FieldName)
{
    if (!Struct || !StructValue)
    {
        return 0;
    }
    const FArrayProperty* Property = CastField<FArrayProperty>(Struct->FindPropertyByName(FieldName));
    if (!Property)
    {
        return 0;
    }
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(StructValue);
    if (!ValuePtr)
    {
        return 0;
    }
    return FScriptArrayHelper(Property, ValuePtr).Num();
}

static int32 GetArrayCount(UObject* Object, const FName FieldName)
{
    return Object ? GetArrayCount(Object->GetClass(), Object, FieldName) : 0;
}

static bool ClassInheritsName(const UClass* Class, const TCHAR* BaseName)
{
    for (const UClass* It = Class; It; It = It->GetSuperClass())
    {
        if (It->GetName().Equals(BaseName, ESearchCase::CaseSensitive))
        {
            return true;
        }
    }
    return false;
}

static FString FamilyForKind(const FString& Kind)
{
    if (Kind.StartsWith(TEXT("level_sequence")) || Kind.StartsWith(TEXT("movie_scene"))) return TEXT("cinematic");
    if (Kind.StartsWith(TEXT("sound_")) || Kind.StartsWith(TEXT("metasound_")) || Kind == TEXT("audio_asset")) return TEXT("audio");
    if (Kind.StartsWith(TEXT("input_")) || Kind.StartsWith(TEXT("enhanced_input"))) return TEXT("input");
    return TEXT("gameplay");
}

static FString DirectKindForClassPath(const FString& ClassPath)
{
    if (ClassPath == TEXT("/Script/LevelSequence.LevelSequence")) return TEXT("level_sequence");

    if (ClassPath == TEXT("/Script/MetasoundEngine.MetaSoundSource")) return TEXT("metasound_source");
    if (ClassPath == TEXT("/Script/MetasoundEngine.MetaSoundPatch")) return TEXT("metasound_patch");
    if (ClassPath == TEXT("/Script/Engine.SoundCue")) return TEXT("sound_cue");
    if (ClassPath == TEXT("/Script/Engine.SoundWave")) return TEXT("sound_wave");
    if (ClassPath == TEXT("/Script/Engine.SoundClass")) return TEXT("sound_class");
    if (ClassPath == TEXT("/Script/Engine.SoundMix")) return TEXT("sound_mix");
    if (ClassPath == TEXT("/Script/Engine.SoundAttenuation")) return TEXT("sound_attenuation");
    if (ClassPath == TEXT("/Script/Engine.SoundConcurrency")) return TEXT("sound_concurrency");

    if (ClassPath == TEXT("/Script/EnhancedInput.InputAction")) return TEXT("input_action");
    if (ClassPath == TEXT("/Script/EnhancedInput.InputMappingContext")) return TEXT("input_mapping_context");
    if (ClassPath == TEXT("/Script/EnhancedInput.PlayerMappableInputConfig")) return TEXT("player_mappable_input_config");
    if (ClassPath == TEXT("/Script/EnhancedInput.EnhancedInputPlatformData")) return TEXT("enhanced_input_platform_data");

    if (ClassPath == TEXT("/Script/Engine.CurveTable")) return TEXT("curve_table");
    if (ClassPath == TEXT("/Script/Engine.CompositeCurveTable")) return TEXT("composite_curve_table");
    if (ClassPath == TEXT("/Script/Engine.PrimaryAssetLabel")) return TEXT("primary_asset_label");
    if (ClassPath == TEXT("/Script/CommonInput.CommonInputActionDomain")) return TEXT("common_input_action_domain");
    if (ClassPath == TEXT("/Script/CommonInput.CommonInputActionDomainTable")) return TEXT("common_input_action_domain_table");
    return FString();
}

static bool IsCandidateClassPath(const FString& ClassPath)
{
    return !DirectKindForClassPath(ClassPath).IsEmpty() ||
        ClassPath == TEXT("/Script/Engine.DataTable") ||
        ClassPath == TEXT("/Script/Engine.CompositeDataTable") ||
        ClassPath.Contains(TEXT("DataTable")) ||
        ClassPath.Contains(TEXT("CurveTable"));
}

static FString KindForLoadedObject(UObject* Object, const FString& ClassPath, bool bPrimaryDataAssetCandidate = false)
{
    FString Kind = DirectKindForClassPath(ClassPath);
    if (!Kind.IsEmpty())
    {
        return Kind;
    }
    if (!Object)
    {
        return FString();
    }

    if (ClassInheritsName(Object->GetClass(), TEXT("LevelSequence"))) return TEXT("level_sequence");
    if (ClassInheritsName(Object->GetClass(), TEXT("SoundCue"))) return TEXT("sound_cue");
    if (ClassInheritsName(Object->GetClass(), TEXT("SoundWave"))) return TEXT("sound_wave");
    if (ClassInheritsName(Object->GetClass(), TEXT("InputAction"))) return TEXT("input_action");
    if (ClassInheritsName(Object->GetClass(), TEXT("InputMappingContext"))) return TEXT("input_mapping_context");

    if (UDataTable* Table = Cast<UDataTable>(Object))
    {
        if (ClassInheritsName(Object->GetClass(), TEXT("MirrorDataTable")))
        {
            // Animation schema 1 owns MirrorDataTable semantics and identity.
            return FString();
        }
        if (const UScriptStruct* RowStruct = Table->GetRowStruct())
        {
            const FString RowStructPath = RowStruct->GetPathName();
            if (RowStructPath.Contains(TEXT("GameplayTagTableRow")))
            {
                return TEXT("gameplay_tag_table");
            }
            if (RowStructPath.Contains(TEXT("CommonInputActionDataBase")))
            {
                return TEXT("common_input_action_table");
            }
        }
        return ClassInheritsName(Object->GetClass(), TEXT("CompositeDataTable"))
            ? TEXT("composite_data_table")
            : TEXT("data_table");
    }
    if (Cast<UCurveTable>(Object))
    {
        return ClassInheritsName(Object->GetClass(), TEXT("CompositeCurveTable"))
            ? TEXT("composite_curve_table")
            : TEXT("curve_table");
    }
    if (bPrimaryDataAssetCandidate || ClassInheritsName(Object->GetClass(), TEXT("PrimaryDataAsset")))
    {
        return TEXT("primary_data_asset");
    }
    return FString();
}

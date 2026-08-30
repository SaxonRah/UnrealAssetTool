static bool SaveSystemsManifest(
    const FString& OutputDir,
    const FCounts& Counts,
    bool bSuccess,
    const FString& Error)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetNumberField(TEXT("schema_version"), SystemsSchemaVersion);
    Root->SetStringField(TEXT("pass"), TEXT("UnrealAssetToolSystems"));
    Root->SetStringField(TEXT("generated_utc"), FDateTime::UtcNow().ToIso8601());
    Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetBoolField(TEXT("success"), bSuccess);
    Root->SetStringField(TEXT("error"), Error);

    TSharedRef<FJsonObject> C = MakeShared<FJsonObject>();
    C->SetNumberField(TEXT("systems_assets"), Counts.Assets);
    C->SetNumberField(TEXT("systems_properties"), Counts.Properties);
    C->SetNumberField(TEXT("systems_references"), Counts.References);
    C->SetNumberField(TEXT("level_sequences"), Counts.LevelSequences);
    C->SetNumberField(TEXT("movie_scene_bindings"), Counts.MovieSceneBindings);
    C->SetNumberField(TEXT("movie_scene_tracks"), Counts.MovieSceneTracks);
    C->SetNumberField(TEXT("movie_scene_sections"), Counts.MovieSceneSections);
    C->SetNumberField(TEXT("movie_scene_channels"), Counts.MovieSceneChannels);
    C->SetNumberField(TEXT("audio_assets"), Counts.AudioAssets);
    C->SetNumberField(TEXT("sound_cue_nodes"), Counts.SoundCueNodes);
    C->SetNumberField(TEXT("metasound_nodes"), Counts.MetaSoundNodes);
    C->SetNumberField(TEXT("metasound_edges"), Counts.MetaSoundEdges);
    C->SetNumberField(TEXT("input_actions"), Counts.InputActions);
    C->SetNumberField(TEXT("input_mapping_contexts"), Counts.InputMappingContexts);
    C->SetNumberField(TEXT("input_mappings"), Counts.InputMappings);
    C->SetNumberField(TEXT("input_processors"), Counts.InputProcessors);
    C->SetNumberField(TEXT("gameplay_data_assets"), Counts.GameplayDataAssets);
    C->SetNumberField(TEXT("gameplay_tags"), Counts.GameplayTags);
    Root->SetObjectField(TEXT("counts"), C);

    static const TCHAR* Names[] = {
        TEXT("systems_assets.jsonl"),
        TEXT("systems_properties.jsonl"),
        TEXT("systems_references.jsonl"),
        TEXT("level_sequences.jsonl"),
        TEXT("movie_scene_bindings.jsonl"),
        TEXT("movie_scene_tracks.jsonl"),
        TEXT("movie_scene_sections.jsonl"),
        TEXT("movie_scene_channels.jsonl"),
        TEXT("audio_assets.jsonl"),
        TEXT("sound_cue_nodes.jsonl"),
        TEXT("metasound_nodes.jsonl"),
        TEXT("metasound_edges.jsonl"),
        TEXT("input_actions.jsonl"),
        TEXT("input_mapping_contexts.jsonl"),
        TEXT("input_mappings.jsonl"),
        TEXT("input_processors.jsonl"),
        TEXT("gameplay_data_assets.jsonl"),
        TEXT("gameplay_tags.jsonl")
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
    return FFileHelper::SaveStringToFile(
        Text,
        *FPaths::Combine(OutputDir, TEXT("systems_manifest.json")),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

static bool RunSystemsScan(FString& OutError)
{
    FString OutputDir;
    FParse::Value(FCommandLine::Get(), TEXT("Output="), OutputDir);
    const FString ProjectDir = NormalizeAbsolutePath(FPaths::ProjectDir());
    if (OutputDir.IsEmpty())
    {
        OutputDir = FPaths::Combine(ProjectDir, TEXT(".uatool"));
    }
    else if (FPaths::IsRelative(OutputDir))
    {
        OutputDir = FPaths::Combine(ProjectDir, OutputDir);
    }
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
        OutError = TEXT("could not create systems JSONL output files");
        SaveSystemsManifest(OutputDir, Counts, false, OutError);
        return false;
    }

    FAssetRegistryModule& AssetRegistryModule =
        FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
    IAssetRegistry& Registry = AssetRegistryModule.Get();
    Registry.SearchAllAssets(true);

    TArray<FAssetData> Assets;
    Registry.GetAllAssets(Assets, true);
    Assets.Sort([](const FAssetData& A, const FAssetData& B)
    {
        return A.GetSoftObjectPath().ToString() < B.GetSoftObjectPath().ToString();
    });

    TSet<FString> SeenStateOwners;
    for (const FAssetData& Asset : Assets)
    {
        const FString ClassPath = Asset.AssetClassPath.ToString();
        if (!IsCandidateClassPath(ClassPath))
        {
            continue;
        }

        FString PackageFilename;
        const bool bHasDiskPackage = FPackageName::DoesPackageExist(
            Asset.PackageName.ToString(),
            &PackageFilename,
            false);
        if (!bIncludeSelf && bHasDiskPackage && !ToolPluginDir.IsEmpty() &&
            IsInsideDirectory(PackageFilename, ToolPluginDir))
        {
            continue;
        }
        if (!bIncludeEngine && (!bHasDiskPackage || !IsInsideDirectory(PackageFilename, ProjectDir)))
        {
            continue;
        }

        UObject* Object = Asset.GetAsset();
        if (!Object)
        {
            continue;
        }
        const FString Kind = KindForLoadedObject(Object, ClassPath);
        if (Kind.IsEmpty())
        {
            continue;
        }
        const FString AssetPath = Asset.GetSoftObjectPath().ToString();

        TSharedRef<FJsonObject> AssetRow = MakeShared<FJsonObject>();
        AssetRow->SetStringField(TEXT("systems_path"), AssetPath);
        AssetRow->SetStringField(TEXT("systems_kind"), Kind);
        AssetRow->SetStringField(TEXT("family"), FamilyForKind(Kind));
        AssetRow->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
        AssetRow->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
        if (!Writers.Assets.Write(AssetRow))
        {
            OutError = TEXT("failed writing systems asset ") + AssetPath;
            SaveSystemsManifest(OutputDir, Counts, false, OutError);
            return false;
        }
        ++Counts.Assets;

        if (!WriteObjectState(Object, AssetPath, Kind, Writers, Counts, SeenStateOwners))
        {
            OutError = TEXT("failed writing systems state for ") + AssetPath;
            SaveSystemsManifest(OutputDir, Counts, false, OutError);
            return false;
        }

        bool bOk = true;
        if (Kind == TEXT("level_sequence"))
        {
            bOk = ScanLevelSequence(Object, Asset, Writers, Counts, SeenStateOwners);
        }
        else if (Kind.StartsWith(TEXT("sound_")) || Kind.StartsWith(TEXT("metasound_")))
        {
            bOk = ScanAudioAsset(Object, Asset, Kind, Writers, Counts, SeenStateOwners);
        }
        else if (Kind == TEXT("input_action"))
        {
            bOk = ScanInputAction(Object, Asset, Writers, Counts, SeenStateOwners);
        }
        else if (Kind == TEXT("input_mapping_context"))
        {
            bOk = ScanInputMappingContext(Object, Asset, Writers, Counts, SeenStateOwners);
        }
        else if (Kind == TEXT("primary_asset_label") ||
                 Kind == TEXT("common_input_action_table") ||
                 Kind == TEXT("gameplay_tag_table"))
        {
            bOk = ScanGameplayDataAsset(Object, Asset, Kind, Writers, Counts);
        }

        if (!bOk)
        {
            OutError = TEXT("failed while scanning systems asset ") + AssetPath;
            SaveSystemsManifest(OutputDir, Counts, false, OutError);
            return false;
        }
    }

    if (!SaveSystemsManifest(OutputDir, Counts, true, FString()))
    {
        OutError = TEXT("could not write systems_manifest.json");
        return false;
    }

    UE_LOG(
        LogTemp,
        Display,
        TEXT("UnrealAssetToolSystems: assets=%lld sequences=%lld tracks=%lld sections=%lld channels=%lld audio=%lld metasound_nodes=%lld metasound_edges=%lld actions=%lld contexts=%lld mappings=%lld gameplay_tags=%lld"),
        Counts.Assets,
        Counts.LevelSequences,
        Counts.MovieSceneTracks,
        Counts.MovieSceneSections,
        Counts.MovieSceneChannels,
        Counts.AudioAssets,
        Counts.MetaSoundNodes,
        Counts.MetaSoundEdges,
        Counts.InputActions,
        Counts.InputMappingContexts,
        Counts.InputMappings,
        Counts.GameplayTags);
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
    if (!RunSystemsScan(Error))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolSystems: %s"), *Error);
    }
}

struct FSystemsScannerBootstrap
{
    FSystemsScannerBootstrap()
    {
        FCoreDelegates::GetOnPostEngineInit().AddStatic(&OnPostEngineInit);
    }
};

static FSystemsScannerBootstrap GSystemsScannerBootstrap;

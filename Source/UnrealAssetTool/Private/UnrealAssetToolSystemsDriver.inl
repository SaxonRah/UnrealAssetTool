static bool SaveSystemsManifest(
    const FString& OutputDir,
    const FCounts& Counts,
    bool bSuccess,
    const FString& Error)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetNumberField(TEXT("schema_version"), 5);
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
    C->SetNumberField(TEXT("data_table_rows"), Counts.DataTableRows);
    C->SetNumberField(TEXT("data_table_fields"), Counts.DataTableFields);
    C->SetNumberField(TEXT("curve_tables"), Counts.CurveTables);
    C->SetNumberField(TEXT("curve_table_rows"), Counts.CurveTableRows);
    C->SetNumberField(TEXT("curve_table_keys"), Counts.CurveTableKeys);
    C->SetNumberField(TEXT("primary_data_assets"), Counts.PrimaryDataAssets);
    C->SetNumberField(TEXT("gameplay_tag_settings"), Counts.GameplayTagSettings);
    C->SetNumberField(TEXT("gameplay_tag_sources"), Counts.GameplayTagSources);
    C->SetNumberField(TEXT("gameplay_tag_dictionary"), Counts.GameplayTagDictionary);
    C->SetNumberField(TEXT("gameplay_tag_redirects"), Counts.GameplayTagRedirects);
    C->SetNumberField(TEXT("mover_blueprints"), GMoverCounts.Blueprints);
    C->SetNumberField(TEXT("mover_components"), GMoverCounts.Components);
    C->SetNumberField(TEXT("mover_modes"), GMoverCounts.Modes);
    C->SetNumberField(TEXT("mover_settings"), GMoverCounts.Settings);
    C->SetNumberField(TEXT("mover_transitions"), GMoverCounts.Transitions);
    C->SetNumberField(TEXT("gameplay_camera_assets"), GGameplayCameraCounts.Assets);
    C->SetNumberField(TEXT("gameplay_camera_rigs"), GGameplayCameraCounts.Rigs);
    C->SetNumberField(TEXT("gameplay_camera_nodes"), GGameplayCameraCounts.Nodes);
    C->SetNumberField(TEXT("gameplay_camera_node_edges"), GGameplayCameraCounts.NodeEdges);
    C->SetNumberField(TEXT("gameplay_camera_transitions"), GGameplayCameraCounts.Transitions);
    C->SetNumberField(TEXT("gameplay_camera_directors"), GGameplayCameraCounts.Directors);
    C->SetNumberField(TEXT("gameplay_camera_rig_references"), GGameplayCameraCounts.RigReferences);
    C->SetNumberField(TEXT("mass_entity_configs"), GMassZoneGraphCounts.EntityConfigs);
    C->SetNumberField(TEXT("mass_entity_traits"), GMassZoneGraphCounts.EntityTraits);
    C->SetNumberField(TEXT("mass_spawners"), GMassZoneGraphCounts.Spawners);
    C->SetNumberField(TEXT("mass_spawner_entity_types"), GMassZoneGraphCounts.SpawnerEntityTypes);
    C->SetNumberField(TEXT("mass_spawner_generators"), GMassZoneGraphCounts.SpawnerGenerators);
    C->SetNumberField(TEXT("mass_spawn_generator_assets"), GMassZoneGraphCounts.SpawnGeneratorAssets);
    C->SetNumberField(TEXT("mass_agent_components"), GMassZoneGraphCounts.AgentComponents);
    C->SetNumberField(TEXT("zonegraph_shapes"), GMassZoneGraphCounts.ZoneShapes);
    C->SetNumberField(TEXT("zonegraph_shape_points"), GMassZoneGraphCounts.ZoneShapePoints);
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
        TEXT("gameplay_tags.jsonl"),
        TEXT("data_table_rows.jsonl"),
        TEXT("data_table_fields.jsonl"),
        TEXT("curve_tables.jsonl"),
        TEXT("curve_table_rows.jsonl"),
        TEXT("curve_table_keys.jsonl"),
        TEXT("primary_data_assets.jsonl"),
        TEXT("gameplay_tag_settings.jsonl"),
        TEXT("gameplay_tag_sources.jsonl"),
        TEXT("gameplay_tag_dictionary.jsonl"),
        TEXT("gameplay_tag_redirects.jsonl"),
        TEXT("mover_blueprints.jsonl"),
        TEXT("mover_components.jsonl"),
        TEXT("mover_modes.jsonl"),
        TEXT("mover_settings.jsonl"),
        TEXT("mover_transitions.jsonl"),
        TEXT("gameplay_camera_assets.jsonl"),
        TEXT("gameplay_camera_rigs.jsonl"),
        TEXT("gameplay_camera_nodes.jsonl"),
        TEXT("gameplay_camera_node_edges.jsonl"),
        TEXT("gameplay_camera_transitions.jsonl"),
        TEXT("gameplay_camera_directors.jsonl"),
        TEXT("gameplay_camera_rig_references.jsonl"),
        TEXT("mass_entity_configs.jsonl"),
        TEXT("mass_entity_traits.jsonl"),
        TEXT("mass_spawners.jsonl"),
        TEXT("mass_spawner_entity_types.jsonl"),
        TEXT("mass_spawner_generators.jsonl"),
        TEXT("mass_spawn_generator_assets.jsonl"),
        TEXT("mass_agent_components.jsonl"),
        TEXT("zonegraph_shapes.jsonl"),
        TEXT("zonegraph_shape_points.jsonl")
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

    GMoverCounts = FMoverCounts();
    GGameplayCameraCounts = FGameplayCameraCounts();
    GMassZoneGraphCounts = FMassZoneGraphCounts();
    FWriters Writers;
    FCounts Counts;
    if (!Writers.Open(OutputDir) ||
        !GMoverWriters.Open(OutputDir) ||
        !GGameplayCameraWriters.Open(OutputDir) ||
        !GMassZoneGraphWriters.Open(OutputDir))
    {
        OutError = TEXT("could not create systems JSONL output files");
        SaveSystemsManifest(OutputDir, Counts, false, OutError);
        return false;
    }

    FAssetRegistryModule& AssetRegistryModule =
        FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
    IAssetRegistry& Registry = AssetRegistryModule.Get();
    Registry.SearchAllAssets(true);

    TArray<FTopLevelAssetPath> PrimaryAssetBases;
    PrimaryAssetBases.Add(UPrimaryDataAsset::StaticClass()->GetClassPathName());
    TSet<FTopLevelAssetPath> ExcludedPrimaryAssetClasses;
    TSet<FTopLevelAssetPath> PrimaryDataAssetClasses;
    Registry.GetDerivedClassNames(
        PrimaryAssetBases,
        ExcludedPrimaryAssetClasses,
        PrimaryDataAssetClasses);
    PrimaryDataAssetClasses.Add(UPrimaryDataAsset::StaticClass()->GetClassPathName());

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
        const bool bPrimaryDataAssetCandidate = PrimaryDataAssetClasses.Contains(Asset.AssetClassPath);
        if (!IsCandidateClassPath(ClassPath) && !bPrimaryDataAssetCandidate)
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
        const FString Kind = KindForLoadedObject(Object, ClassPath, bPrimaryDataAssetCandidate);
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
        else if (UDataTable* DataTable = Cast<UDataTable>(Object))
        {
            bOk = ScanGameplayDataAsset(Object, Asset, Kind, Writers, Counts) &&
                ScanDataTableDetails(DataTable, Asset, Kind, Writers, Counts);
        }
        else if (UCurveTable* CurveTable = Cast<UCurveTable>(Object))
        {
            bOk = ScanCurveTableDetails(CurveTable, Asset, Kind, Writers, Counts);
        }
        else if (Kind == TEXT("primary_data_asset"))
        {
            bOk = ScanPrimaryDataAsset(Object, Asset, Kind, Writers, Counts);
        }
        else if (Kind == TEXT("primary_asset_label"))
        {
            bOk = ScanGameplayDataAsset(Object, Asset, Kind, Writers, Counts) &&
                ScanPrimaryDataAsset(Object, Asset, Kind, Writers, Counts);
        }
        else if (Kind == TEXT("common_input_action_domain") ||
                 Kind == TEXT("common_input_action_domain_table"))
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

    if (!ScanGameplayTagProjectModel(Writers, Counts))
    {
        OutError = TEXT("failed while scanning project Gameplay Tags model");
        SaveSystemsManifest(OutputDir, Counts, false, OutError);
        return false;
    }

    if (!ScanMoverProjectModel(
            Assets,
            ProjectDir,
            bIncludeEngine,
            bIncludeSelf,
            ToolPluginDir,
            Writers,
            Counts,
            SeenStateOwners,
            OutError))
    {
        SaveSystemsManifest(OutputDir, Counts, false, OutError);
        return false;
    }

    if (!ScanGameplayCameraProjectModel(
            Assets,
            ProjectDir,
            bIncludeEngine,
            bIncludeSelf,
            ToolPluginDir,
            Writers,
            Counts,
            SeenStateOwners,
            OutError))
    {
        SaveSystemsManifest(OutputDir, Counts, false, OutError);
        return false;
    }

    if (!ScanMassZoneGraphProjectModel(
            Assets,
            ProjectDir,
            bIncludeEngine,
            bIncludeSelf,
            ToolPluginDir,
            Writers,
            Counts,
            SeenStateOwners,
            OutError))
    {
        SaveSystemsManifest(OutputDir, Counts, false, OutError);
        return false;
    }

    if (!SaveSystemsManifest(OutputDir, Counts, true, FString()))
    {
        OutError = TEXT("could not write systems_manifest.json");
        return false;
    }

    UE_LOG(
        LogTemp,
        Display,
        TEXT("UnrealAssetToolSystems: assets=%lld sequences=%lld audio=%lld actions=%lld contexts=%lld mappings=%lld data_rows=%lld data_fields=%lld curve_tables=%lld curve_rows=%lld curve_keys=%lld primary_data=%lld tag_sources=%lld tag_dictionary=%lld mover_blueprints=%lld mover_components=%lld mover_modes=%lld mover_settings=%lld mover_transitions=%lld camera_assets=%lld camera_rigs=%lld camera_nodes=%lld camera_node_edges=%lld camera_transitions=%lld camera_directors=%lld camera_rig_refs=%lld mass_configs=%lld mass_traits=%lld mass_spawners=%lld mass_entity_types=%lld mass_generators=%lld mass_generator_assets=%lld mass_agents=%lld zone_shapes=%lld zone_points=%lld"),
        Counts.Assets,
        Counts.LevelSequences,
        Counts.AudioAssets,
        Counts.InputActions,
        Counts.InputMappingContexts,
        Counts.InputMappings,
        Counts.DataTableRows,
        Counts.DataTableFields,
        Counts.CurveTables,
        Counts.CurveTableRows,
        Counts.CurveTableKeys,
        Counts.PrimaryDataAssets,
        Counts.GameplayTagSources,
        Counts.GameplayTagDictionary,
        GMoverCounts.Blueprints,
        GMoverCounts.Components,
        GMoverCounts.Modes,
        GMoverCounts.Settings,
        GMoverCounts.Transitions,
        GGameplayCameraCounts.Assets,
        GGameplayCameraCounts.Rigs,
        GGameplayCameraCounts.Nodes,
        GGameplayCameraCounts.NodeEdges,
        GGameplayCameraCounts.Transitions,
        GGameplayCameraCounts.Directors,
        GGameplayCameraCounts.RigReferences,
        GMassZoneGraphCounts.EntityConfigs,
        GMassZoneGraphCounts.EntityTraits,
        GMassZoneGraphCounts.Spawners,
        GMassZoneGraphCounts.SpawnerEntityTypes,
        GMassZoneGraphCounts.SpawnerGenerators,
        GMassZoneGraphCounts.SpawnGeneratorAssets,
        GMassZoneGraphCounts.AgentComponents,
        GMassZoneGraphCounts.ZoneShapes,
        GMassZoneGraphCounts.ZoneShapePoints);
    return true;
}

static void OnPostEngineInit()
{
    FString RunCommandlet;
    FParse::Value(FCommandLine::Get(), TEXT("run="), RunCommandlet);
    const bool bSystemsOnly = FParse::Param(FCommandLine::Get(), TEXT("UnrealAssetToolSystemsOnly"));
    if (!bSystemsOnly && !RunCommandlet.Equals(TEXT("UnrealAssetToolWorld"), ESearchCase::IgnoreCase))
    {
        return;
    }

    FString Error;
    const bool bSuccess = RunSystemsScan(Error);
    if (!bSuccess)
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolSystems: %s"), *Error);
    }

    if (bSystemsOnly)
    {
        UE_LOG(
            LogTemp,
            Display,
            TEXT("UnrealAssetToolSystems: isolated systems capture complete; requesting editor exit"));
        FPlatformMisc::RequestExit(false);
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

static void GatherDataflowChaosCandidates(
    const TArray<FAssetData>& ExistingAssets,
    TArray<FAssetData>& OutAssets)
{
    FAssetRegistryModule& AssetRegistryModule =
        FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
    IAssetRegistry& Registry = AssetRegistryModule.Get();

    Registry.WaitForPremadeAssetRegistry();
    TArray<FString> ProjectPaths;
    ProjectPaths.Add(TEXT("/Game"));
    Registry.ScanPathsSynchronous(ProjectPaths, true, true);
    Registry.WaitForCompletion();

    TArray<FAssetData> RegistryAssets;
    Registry.GetAssetsByClass(UDataflow::StaticClass()->GetClassPathName(), RegistryAssets, false);
    const FTopLevelAssetPath GeometryCollectionClassPath(
        TEXT("/Script/GeometryCollectionEngine"),
        TEXT("GeometryCollection"));
    Registry.GetAssetsByClass(GeometryCollectionClassPath, RegistryAssets, false);

    TSet<FString> Seen;
    auto AddCandidate = [&OutAssets, &Seen](const FAssetData& Asset)
    {
        const FString ClassPath = Asset.AssetClassPath.ToString();
        if (ClassPath != TEXT("/Script/DataflowEngine.Dataflow") &&
            ClassPath != TEXT("/Script/GeometryCollectionEngine.GeometryCollection"))
        {
            return;
        }
        const FString Path = Asset.GetSoftObjectPath().ToString();
        if (Path.IsEmpty() || Seen.Contains(Path)) return;
        Seen.Add(Path);
        OutAssets.Add(Asset);
    };

    for (const FAssetData& Asset : RegistryAssets) AddCandidate(Asset);
    for (const FAssetData& Asset : ExistingAssets) AddCandidate(Asset);

    OutAssets.Sort([](const FAssetData& A, const FAssetData& B)
    {
        return A.GetSoftObjectPath().ToString() < B.GetSoftObjectPath().ToString();
    });
}

static bool ScanDataflowChaosProjectModelExactLoad(
    const TArray<FAssetData>& Assets,
    const FString& ProjectDir,
    bool bIncludeEngine,
    bool bIncludeSelf,
    const FString& ToolPluginDir,
    FString& OutError)
{
    TArray<FAssetData> Candidates;
    GatherDataflowChaosCandidates(Assets, Candidates);
    for (const FAssetData& Asset : Candidates)
    {
        ++GDataflowChaosCounts.Candidates;
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
        ++GDataflowChaosCounts.ScopedCandidates;
        if (!DataflowChaosScanLoadedAsset(Asset.GetSoftObjectPath().ToString(), OutError))
        {
            return false;
        }
    }
    return true;
}

static bool ScanGASSmartObjectsAIPerceptionAndDataflowChaosProjectModels(
    const TArray<FAssetData>& Assets,
    const FString& ProjectDir,
    bool bIncludeEngine,
    bool bIncludeSelf,
    const FString& ToolPluginDir,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners,
    FString& OutError)
{
    GDataflowChaosCounts = FDataflowChaosCounts();
    const FString OutputDir = SmartObjectSystemsOutputDir();
    if (!GDataflowChaosWriters.Open(OutputDir))
    {
        OutError = TEXT("could not create Dataflow/Geometry Collection systems JSONL output files");
        GDataflowChaosWriters = FDataflowChaosWriters();
        return false;
    }

    const bool bDataflowChaosOk = ScanDataflowChaosProjectModelExactLoad(
        Assets,
        ProjectDir,
        bIncludeEngine,
        bIncludeSelf,
        ToolPluginDir,
        OutError);

    // Destroy specialist archives before the authoritative manifest is written.
    GDataflowChaosWriters = FDataflowChaosWriters();
    if (!bDataflowChaosOk) return false;

    return ScanGASSmartObjectsAndAIPerceptionProjectModels(
        Assets,
        ProjectDir,
        bIncludeEngine,
        bIncludeSelf,
        ToolPluginDir,
        Writers,
        Counts,
        SeenStateOwners,
        OutError);
}

static bool UpgradeSystemsManifestToSchema9(const FString& ManifestPath)
{
    FString Text;
    if (!FFileHelper::LoadFileToString(Text, *ManifestPath)) return false;

    TSharedPtr<FJsonObject> Root;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
    if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid()) return false;
    Root->SetNumberField(TEXT("schema_version"), 9);

    TSharedPtr<FJsonObject> Counts;
    const TSharedPtr<FJsonObject>* CountsField = nullptr;
    if (Root->TryGetObjectField(TEXT("counts"), CountsField) && CountsField && CountsField->IsValid())
    {
        Counts = *CountsField;
    }
    else
    {
        Counts = MakeShared<FJsonObject>();
        Root->SetObjectField(TEXT("counts"), Counts.ToSharedRef());
    }

    Counts->SetNumberField(TEXT("dataflow_chaos_candidates"), GDataflowChaosCounts.Candidates);
    Counts->SetNumberField(TEXT("dataflow_chaos_scoped_candidates"), GDataflowChaosCounts.ScopedCandidates);
    Counts->SetNumberField(TEXT("dataflow_chaos_loaded_assets"), GDataflowChaosCounts.LoadedAssets);
    Counts->SetNumberField(TEXT("dataflow_assets"), GDataflowChaosCounts.DataflowAssets);
    Counts->SetNumberField(TEXT("geometry_collections"), GDataflowChaosCounts.GeometryCollections);
    Counts->SetNumberField(TEXT("dataflow_graphs"), GDataflowChaosCounts.Graphs);
    Counts->SetNumberField(TEXT("dataflow_nodes"), GDataflowChaosCounts.Nodes);
    Counts->SetNumberField(TEXT("dataflow_pins"), GDataflowChaosCounts.Pins);
    Counts->SetNumberField(TEXT("dataflow_edges"), GDataflowChaosCounts.Edges);
    Counts->SetNumberField(TEXT("dataflow_asset_properties"), GDataflowChaosCounts.DataflowAssetProperties);
    Counts->SetNumberField(TEXT("dataflow_asset_references"), GDataflowChaosCounts.DataflowAssetReferences);
    Counts->SetNumberField(TEXT("dataflow_node_properties"), GDataflowChaosCounts.NodeProperties);
    Counts->SetNumberField(TEXT("dataflow_node_references"), GDataflowChaosCounts.NodeReferences);
    Counts->SetNumberField(TEXT("geometry_collection_properties"), GDataflowChaosCounts.GeometryCollectionProperties);
    Counts->SetNumberField(TEXT("geometry_collection_references"), GDataflowChaosCounts.GeometryCollectionReferences);
    Counts->SetNumberField(TEXT("dataflow_chaos_truncated_properties"), GDataflowChaosCounts.TruncatedProperties);
    Counts->SetNumberField(TEXT("dataflow_chaos_property_row_limit_hits"), GDataflowChaosCounts.PropertyRowLimitHits);

    TArray<TSharedPtr<FJsonValue>> Files;
    const TArray<TSharedPtr<FJsonValue>>* ExistingFiles = nullptr;
    if (Root->TryGetArrayField(TEXT("files"), ExistingFiles) && ExistingFiles) Files = *ExistingFiles;
    TSet<FString> ExistingNames;
    for (const TSharedPtr<FJsonValue>& Value : Files)
    {
        FString Name;
        if (Value.IsValid() && Value->TryGetString(Name)) ExistingNames.Add(Name);
    }
    static const TCHAR* DataflowChaosFiles[] = {
        TEXT("dataflow_graphs.jsonl"),
        TEXT("dataflow_nodes.jsonl"),
        TEXT("dataflow_pins.jsonl"),
        TEXT("dataflow_edges.jsonl"),
        TEXT("dataflow_asset_properties.jsonl"),
        TEXT("dataflow_asset_references.jsonl"),
        TEXT("dataflow_node_properties.jsonl"),
        TEXT("dataflow_node_references.jsonl"),
        TEXT("geometry_collections.jsonl"),
        TEXT("geometry_collection_properties.jsonl"),
        TEXT("geometry_collection_references.jsonl")
    };
    for (const TCHAR* Name : DataflowChaosFiles)
    {
        if (!ExistingNames.Contains(Name)) Files.Add(MakeShared<FJsonValueString>(Name));
    }
    Root->SetArrayField(TEXT("files"), Files);

    FString Updated;
    const TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer =
        TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Updated);
    if (!FJsonSerializer::Serialize(Root.ToSharedRef(), Writer)) return false;
    if (!FFileHelper::SaveStringToFile(
            Updated,
            *ManifestPath,
            FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
    {
        return false;
    }

    UE_LOG(
        LogTemp,
        Display,
        TEXT("UnrealAssetToolSystems: synchronously promoted systems manifest to schema 9 candidates=%lld scoped=%lld loaded=%lld dataflows=%lld geometry_collections=%lld graphs=%lld nodes=%lld pins=%lld edges=%lld node_properties=%lld gc_properties=%lld truncated=%lld row_limit_hits=%lld"),
        GDataflowChaosCounts.Candidates,
        GDataflowChaosCounts.ScopedCandidates,
        GDataflowChaosCounts.LoadedAssets,
        GDataflowChaosCounts.DataflowAssets,
        GDataflowChaosCounts.GeometryCollections,
        GDataflowChaosCounts.Graphs,
        GDataflowChaosCounts.Nodes,
        GDataflowChaosCounts.Pins,
        GDataflowChaosCounts.Edges,
        GDataflowChaosCounts.NodeProperties,
        GDataflowChaosCounts.GeometryCollectionProperties,
        GDataflowChaosCounts.TruncatedProperties,
        GDataflowChaosCounts.PropertyRowLimitHits);
    return true;
}

struct FDataflowChaosSystemsFileHelperProxy
{
    using EEncodingOptions = FFileHelper::EEncodingOptions;

    static bool SaveStringToFile(
        const FString& String,
        const TCHAR* Filename,
        EEncodingOptions EncodingOptions)
    {
        if (!FAIPerceptionSystemsFileHelperProxy::SaveStringToFile(String, Filename, EncodingOptions))
        {
            return false;
        }
        const FString Path = Filename ? FString(Filename) : FString();
        if (!FPaths::GetCleanFilename(Path).Equals(TEXT("systems_manifest.json"), ESearchCase::IgnoreCase))
        {
            return true;
        }
        return UpgradeSystemsManifestToSchema9(Path);
    }
};

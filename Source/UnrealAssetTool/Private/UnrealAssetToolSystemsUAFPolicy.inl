static void EnsureUAFRepresentativeMounts()
{
    struct FMountSpec
    {
        const TCHAR* PluginName;
        const TCHAR* RootPath;
    };
    static const FMountSpec MountSpecs[] = {
        { TEXT("UAF"), TEXT("/UAF/") },
        { TEXT("UAFAnimGraph"), TEXT("/UAFAnimGraph/") },
        { TEXT("UAFSharedAssets"), TEXT("/UAFSharedAssets/") },
    };

    for (const FMountSpec& Spec : MountSpecs)
    {
        const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(Spec.PluginName);
        if (!Plugin.IsValid())
        {
            UE_LOG(LogTemp, Warning,
                TEXT("UnrealAssetToolSystems: requested UAF representative plugin is unavailable: %s"),
                Spec.PluginName);
            continue;
        }

        FString RootPath = Plugin->GetMountedAssetPath();
        if (RootPath.IsEmpty()) RootPath = Spec.RootPath;
        if (!RootPath.EndsWith(TEXT("/"))) RootPath += TEXT("/");

        bool bPackageMounted = FPackageName::MountPointExists(RootPath);
        UE_LOG(LogTemp, Display,
            TEXT("UnrealAssetToolSystems: UAF mount status plugin=%s enabled=%d plugin_mounted=%d package_mounted=%d root=%s content=%s"),
            Spec.PluginName,
            Plugin->IsEnabled() ? 1 : 0,
            Plugin->IsMounted() ? 1 : 0,
            bPackageMounted ? 1 : 0,
            *RootPath,
            *Plugin->GetContentDir());

        if (!bPackageMounted)
        {
            FPackageName::RegisterMountPoint(RootPath, Plugin->GetContentDir());
            bPackageMounted = FPackageName::MountPointExists(RootPath);
            UE_LOG(LogTemp, Display,
                TEXT("UnrealAssetToolSystems: registered UAF representative mount plugin=%s mounted=%d root=%s"),
                Spec.PluginName,
                bPackageMounted ? 1 : 0,
                *RootPath);
        }
    }
}

static void GatherUAFCandidates(const TArray<FAssetData>& ExistingAssets, TArray<FAssetData>& OutAssets)
{
    FAssetRegistryModule& AssetRegistryModule =
        FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
    IAssetRegistry& Registry = AssetRegistryModule.Get();
    Registry.WaitForPremadeAssetRegistry();

    const bool bUAFEngineContent = FParse::Param(FCommandLine::Get(), TEXT("UAFEngineContent"));
    TArray<FString> ScanPaths;
    ScanPaths.Add(TEXT("/Game"));
    TArray<FString> RepresentativePaths;
    if (bUAFEngineContent)
    {
        EnsureUAFRepresentativeMounts();
        RepresentativePaths.Add(TEXT("/UAF"));
        RepresentativePaths.Add(TEXT("/UAFAnimGraph"));
        RepresentativePaths.Add(TEXT("/UAFSharedAssets"));
        ScanPaths.Append(RepresentativePaths);
    }
    Registry.ScanPathsSynchronous(ScanPaths, true, true);
    Registry.WaitForCompletion();

    TSet<FString> Seen;
    auto AddCandidate = [&OutAssets, &Seen](const FAssetData& Asset, bool bRequireExactRegistryClass)
    {
        if (bRequireExactRegistryClass && !UAFIsExactAssetClass(Asset.AssetClassPath.ToString())) return;
        const FString Path = Asset.GetSoftObjectPath().ToString();
        if (Path.IsEmpty() || Seen.Contains(Path)) return;
        Seen.Add(Path);
        OutAssets.Add(Asset);
    };

    // The accepted focused UAF evidence deliberately discovered every asset in
    // these three explicit mount roots, loaded each object, and only then used
    // the exact loaded UObject class to decide whether it was first-class UAF.
    // Do the same here. Asset Registry class identity is useful for cheap
    // project-wide discovery, but it is not authoritative for this installed
    // representative corpus.
    for (const FString& Path : RepresentativePaths)
    {
        FARFilter Filter;
        Filter.PackagePaths.Add(FName(*Path));
        Filter.bRecursivePaths = true;
        TArray<FAssetData> PathAssets;
        Registry.GetAssets(Filter, PathAssets);
        for (const FAssetData& Asset : PathAssets) AddCandidate(Asset, false);
    }

    // Normal project-wide discovery stays narrow. Exact first-class identity is
    // still re-checked from Asset->GetClass() after load in UAFScanLoadedAsset.
    for (const FAssetData& Asset : ExistingAssets) AddCandidate(Asset, true);
    OutAssets.Sort([](const FAssetData& A, const FAssetData& B)
    {
        return A.GetSoftObjectPath().ToString() < B.GetSoftObjectPath().ToString();
    });
}

static bool ScanUAFProjectModelExactLoad(
    const TArray<FAssetData>& Assets,
    const FString& ProjectDir,
    bool bIncludeEngine,
    bool bIncludeSelf,
    const FString& ToolPluginDir,
    FString& OutError)
{
    TArray<FAssetData> Candidates;
    GatherUAFCandidates(Assets, Candidates);
    const bool bUAFEngineContent = FParse::Param(FCommandLine::Get(), TEXT("UAFEngineContent"));
    for (const FAssetData& Asset : Candidates)
    {
        ++GUAFCounts.Candidates;
        FString PackageFilename;
        const bool bHasDiskPackage = FPackageName::DoesPackageExist(Asset.PackageName.ToString(), &PackageFilename, false);
        if (!bIncludeSelf && bHasDiskPackage && !ToolPluginDir.IsEmpty() && IsInsideDirectory(PackageFilename, ToolPluginDir))
            continue;

        const FString ObjectPath = Asset.GetSoftObjectPath().ToString();
        const bool bRepresentativeEngineAsset = bUAFEngineContent &&
            (ObjectPath.StartsWith(TEXT("/UAF/")) ||
             ObjectPath.StartsWith(TEXT("/UAFAnimGraph/")) ||
             ObjectPath.StartsWith(TEXT("/UAFSharedAssets/")));
        if (!bIncludeEngine && !bRepresentativeEngineAsset &&
            (!bHasDiskPackage || !IsInsideDirectory(PackageFilename, ProjectDir)))
        {
            continue;
        }
        ++GUAFCounts.ScopedCandidates;
        if (!UAFScanLoadedAsset(ObjectPath, OutError)) return false;
    }
    return true;
}

static bool ScanGASSmartObjectsAIPerceptionDataflowChaosAndUAFProjectModels(
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
    GUAFCounts = FUAFCounts();
    const FString OutputDir = SmartObjectSystemsOutputDir();
    if (!GUAFWriters.Open(OutputDir))
    {
        OutError = TEXT("could not create UAF systems JSONL output files");
        GUAFWriters = FUAFWriters();
        return false;
    }

    const bool bUAFOk = ScanUAFProjectModelExactLoad(
        Assets, ProjectDir, bIncludeEngine, bIncludeSelf, ToolPluginDir, OutError);
    GUAFWriters = FUAFWriters();
    if (!bUAFOk) return false;

    return ScanGASSmartObjectsAIPerceptionAndDataflowChaosProjectModels(
        Assets, ProjectDir, bIncludeEngine, bIncludeSelf, ToolPluginDir,
        Writers, Counts, SeenStateOwners, OutError);
}

static bool UpgradeSystemsManifestToSchema10(const FString& ManifestPath)
{
    FString Text;
    if (!FFileHelper::LoadFileToString(Text, *ManifestPath)) return false;
    TSharedPtr<FJsonObject> Root;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
    if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid()) return false;
    Root->SetNumberField(TEXT("schema_version"), 10);

    TSharedPtr<FJsonObject> Counts;
    const TSharedPtr<FJsonObject>* CountsField = nullptr;
    if (Root->TryGetObjectField(TEXT("counts"), CountsField) && CountsField && CountsField->IsValid())
        Counts = *CountsField;
    else
    {
        Counts = MakeShared<FJsonObject>();
        Root->SetObjectField(TEXT("counts"), Counts.ToSharedRef());
    }
    Counts->SetNumberField(TEXT("uaf_candidates"), GUAFCounts.Candidates);
    Counts->SetNumberField(TEXT("uaf_scoped_candidates"), GUAFCounts.ScopedCandidates);
    Counts->SetNumberField(TEXT("uaf_loaded_assets"), GUAFCounts.LoadedAssets);
    Counts->SetNumberField(TEXT("uaf_assets"), GUAFCounts.Assets);
    Counts->SetNumberField(TEXT("uaf_entries"), GUAFCounts.Entries);
    Counts->SetNumberField(TEXT("uaf_variables"), GUAFCounts.Variables);
    Counts->SetNumberField(TEXT("uaf_components"), GUAFCounts.Components);
    Counts->SetNumberField(TEXT("uaf_entry_points"), GUAFCounts.EntryPoints);
    Counts->SetNumberField(TEXT("uaf_rigvm_graphs"), GUAFCounts.RigVMGraphs);
    Counts->SetNumberField(TEXT("uaf_rigvm_nodes"), GUAFCounts.RigVMNodes);
    Counts->SetNumberField(TEXT("uaf_rigvm_pins"), GUAFCounts.RigVMPins);
    Counts->SetNumberField(TEXT("uaf_rigvm_links"), GUAFCounts.RigVMLinks);
    Counts->SetNumberField(TEXT("uaf_variable_usages"), GUAFCounts.VariableUsages);
    Counts->SetNumberField(TEXT("uaf_truncated_values"), GUAFCounts.TruncatedValues);

    TArray<TSharedPtr<FJsonValue>> Files;
    const TArray<TSharedPtr<FJsonValue>>* ExistingFiles = nullptr;
    if (Root->TryGetArrayField(TEXT("files"), ExistingFiles) && ExistingFiles) Files = *ExistingFiles;
    TSet<FString> ExistingNames;
    for (const TSharedPtr<FJsonValue>& Value : Files)
    {
        FString Name;
        if (Value.IsValid() && Value->TryGetString(Name)) ExistingNames.Add(Name);
    }
    static const TCHAR* UAFFiles[] = {
        TEXT("uaf_assets.jsonl"), TEXT("uaf_entries.jsonl"), TEXT("uaf_variables.jsonl"),
        TEXT("uaf_components.jsonl"), TEXT("uaf_entry_points.jsonl"),
        TEXT("uaf_rigvm_graphs.jsonl"), TEXT("uaf_rigvm_nodes.jsonl"),
        TEXT("uaf_rigvm_pins.jsonl"), TEXT("uaf_rigvm_links.jsonl"),
        TEXT("uaf_variable_usages.jsonl")
    };
    for (const TCHAR* Name : UAFFiles)
        if (!ExistingNames.Contains(Name)) Files.Add(MakeShared<FJsonValueString>(Name));
    Root->SetArrayField(TEXT("files"), Files);

    FString Updated;
    const TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer =
        TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Updated);
    if (!FJsonSerializer::Serialize(Root.ToSharedRef(), Writer)) return false;
    if (!FFileHelper::SaveStringToFile(Updated, *ManifestPath, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
        return false;

    UE_LOG(LogTemp, Display,
        TEXT("UnrealAssetToolSystems: promoted systems manifest to schema 10 UAF candidates=%lld scoped=%lld loaded=%lld assets=%lld entries=%lld variables=%lld components=%lld entry_points=%lld graphs=%lld nodes=%lld pins=%lld links=%lld variable_usages=%lld truncated=%lld"),
        GUAFCounts.Candidates, GUAFCounts.ScopedCandidates, GUAFCounts.LoadedAssets,
        GUAFCounts.Assets, GUAFCounts.Entries, GUAFCounts.Variables, GUAFCounts.Components,
        GUAFCounts.EntryPoints, GUAFCounts.RigVMGraphs, GUAFCounts.RigVMNodes,
        GUAFCounts.RigVMPins, GUAFCounts.RigVMLinks, GUAFCounts.VariableUsages,
        GUAFCounts.TruncatedValues);
    return true;
}

struct FUAFSystemsFileHelperProxy
{
    using EEncodingOptions = FFileHelper::EEncodingOptions;
    static bool SaveStringToFile(const FString& String, const TCHAR* Filename, EEncodingOptions EncodingOptions)
    {
        if (!FDataflowChaosSystemsFileHelperProxy::SaveStringToFile(String, Filename, EncodingOptions))
            return false;
        const FString Path = Filename ? FString(Filename) : FString();
        if (!FPaths::GetCleanFilename(Path).Equals(TEXT("systems_manifest.json"), ESearchCase::IgnoreCase))
            return true;
        return UpgradeSystemsManifestToSchema10(Path);
    }
};

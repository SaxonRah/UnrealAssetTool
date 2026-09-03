static bool ScanGASSmartObjectsAIPerceptionDataflowChaosUAFAndNavigationProjectModels(
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
    GNavigationCounts = FNavigationCounts();
    const FString OutputDir = SmartObjectSystemsOutputDir();
    if (!GNavigationWriters.Open(OutputDir))
    {
        OutError = TEXT("could not create Navigation systems JSONL output files");
        GNavigationWriters = FNavigationWriters();
        return false;
    }

    const bool bNavigationOk = ScanNavigationProjectModel(OutError);
    GNavigationWriters = FNavigationWriters();
    if (!bNavigationOk) return false;

    return ScanGASSmartObjectsAIPerceptionDataflowChaosAndUAFProjectModels(
        Assets, ProjectDir, bIncludeEngine, bIncludeSelf, ToolPluginDir,
        Writers, Counts, SeenStateOwners, OutError);
}

static bool UpgradeSystemsManifestToSchema11(const FString& ManifestPath)
{
    FString Text;
    if (!FFileHelper::LoadFileToString(Text, *ManifestPath)) return false;
    TSharedPtr<FJsonObject> Root;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
    if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid()) return false;
    Root->SetNumberField(TEXT("schema_version"), 11);

    TSharedPtr<FJsonObject> Counts;
    const TSharedPtr<FJsonObject>* CountsField = nullptr;
    if (Root->TryGetObjectField(TEXT("counts"), CountsField) && CountsField && CountsField->IsValid())
        Counts = *CountsField;
    else
    {
        Counts = MakeShared<FJsonObject>();
        Root->SetObjectField(TEXT("counts"), Counts.ToSharedRef());
    }

    Counts->SetNumberField(TEXT("navigation_areas"), GNavigationCounts.Areas);
    Counts->SetNumberField(TEXT("navigation_area_agent_mappings"), GNavigationCounts.AreaAgentMappings);
    Counts->SetNumberField(TEXT("navigation_systems"), GNavigationCounts.Systems);
    Counts->SetNumberField(TEXT("navigation_agents"), GNavigationCounts.Agents);
    Counts->SetNumberField(TEXT("navigation_link_defaults"), GNavigationCounts.LinkDefaults);
    Counts->SetNumberField(TEXT("navigation_modifier_defaults"), GNavigationCounts.ModifierDefaults);
    Counts->SetNumberField(TEXT("navigation_invoker_defaults"), GNavigationCounts.InvokerDefaults);
    Counts->SetNumberField(TEXT("navigation_bounds_defaults"), GNavigationCounts.BoundsDefaults);
    Counts->SetNumberField(TEXT("navigation_recast_defaults"), GNavigationCounts.RecastDefaults);
    Counts->SetNumberField(TEXT("navigation_truncated_values"), GNavigationCounts.TruncatedValues);
    Counts->SetNumberField(TEXT("navigation_missing_expected_classes"), GNavigationCounts.MissingExpectedClasses);

    TArray<TSharedPtr<FJsonValue>> Files;
    const TArray<TSharedPtr<FJsonValue>>* ExistingFiles = nullptr;
    if (Root->TryGetArrayField(TEXT("files"), ExistingFiles) && ExistingFiles) Files = *ExistingFiles;
    TSet<FString> ExistingNames;
    for (const TSharedPtr<FJsonValue>& Value : Files)
    {
        FString Name;
        if (Value.IsValid() && Value->TryGetString(Name)) ExistingNames.Add(Name);
    }

    static const TCHAR* NavigationFiles[] = {
        TEXT("navigation_areas.jsonl"),
        TEXT("navigation_area_agent_mappings.jsonl"),
        TEXT("navigation_systems.jsonl"),
        TEXT("navigation_agents.jsonl"),
        TEXT("navigation_link_defaults.jsonl"),
        TEXT("navigation_modifier_defaults.jsonl"),
        TEXT("navigation_invoker_defaults.jsonl"),
        TEXT("navigation_bounds_defaults.jsonl"),
        TEXT("navigation_recast_defaults.jsonl"),
    };
    for (const TCHAR* Name : NavigationFiles)
        if (!ExistingNames.Contains(Name)) Files.Add(MakeShared<FJsonValueString>(Name));
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

    UE_LOG(LogTemp, Display,
        TEXT("UnrealAssetToolSystems: promoted systems manifest to schema 11 Navigation areas=%lld mappings=%lld systems=%lld agents=%lld links=%lld modifiers=%lld invokers=%lld bounds=%lld recast=%lld truncated=%lld missing=%lld"),
        GNavigationCounts.Areas,
        GNavigationCounts.AreaAgentMappings,
        GNavigationCounts.Systems,
        GNavigationCounts.Agents,
        GNavigationCounts.LinkDefaults,
        GNavigationCounts.ModifierDefaults,
        GNavigationCounts.InvokerDefaults,
        GNavigationCounts.BoundsDefaults,
        GNavigationCounts.RecastDefaults,
        GNavigationCounts.TruncatedValues,
        GNavigationCounts.MissingExpectedClasses);
    return true;
}

struct FNavigationSystemsFileHelperProxy
{
    using EEncodingOptions = FFileHelper::EEncodingOptions;
    static bool SaveStringToFile(
        const FString& String,
        const TCHAR* Filename,
        EEncodingOptions EncodingOptions)
    {
        if (!FUAFSystemsFileHelperProxy::SaveStringToFile(String, Filename, EncodingOptions))
            return false;
        const FString Path = Filename ? FString(Filename) : FString();
        if (!FPaths::GetCleanFilename(Path).Equals(
                TEXT("systems_manifest.json"),
                ESearchCase::IgnoreCase))
        {
            return true;
        }
        return UpgradeSystemsManifestToSchema11(Path);
    }
};

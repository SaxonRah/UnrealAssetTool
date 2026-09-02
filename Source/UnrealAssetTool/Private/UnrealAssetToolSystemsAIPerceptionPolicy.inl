static int64 GAIPerceptionBlueprintCandidates = 0;
static int64 GAIPerceptionScopedBlueprintCandidates = 0;
static int64 GAIPerceptionLoadedBlueprints = 0;
static int64 GAIPerceptionGeneratedClasses = 0;
static int64 GAIPerceptionScannedBlueprints = 0;

static bool ScanAIPerceptionProjectModelExactLoad(
    const TArray<FAssetData>& Assets,
    const FString& ProjectDir,
    bool bIncludeEngine,
    bool bIncludeSelf,
    const FString& ToolPluginDir,
    FString& OutError)
{
    for (const FAssetData& Asset : Assets)
    {
        const FString AssetClassPath = Asset.AssetClassPath.ToString();
        const bool bBlueprintCandidate =
            Asset.AssetClassPath == UBlueprint::StaticClass()->GetClassPathName() ||
            AIPerceptionBlueprintCandidate(Asset);
        if (!bBlueprintCandidate)
        {
            continue;
        }
        ++GAIPerceptionBlueprintCandidates;

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
        ++GAIPerceptionScopedBlueprintCandidates;

        const FString BlueprintPath = Asset.GetSoftObjectPath().ToString();
        UObject* AssetObject = StaticLoadObject(UObject::StaticClass(), nullptr, *BlueprintPath);
        UBlueprint* Blueprint = Cast<UBlueprint>(AssetObject);
        if (!Blueprint)
        {
            continue;
        }
        ++GAIPerceptionLoadedBlueprints;

        if (!Blueprint->GeneratedClass.Get())
        {
            continue;
        }
        ++GAIPerceptionGeneratedClasses;

        if (!ScanAIPerceptionBlueprint(Asset, Blueprint, OutError))
        {
            return false;
        }
        ++GAIPerceptionScannedBlueprints;
    }
    return true;
}

static bool ScanGASSmartObjectsAndAIPerceptionProjectModels(
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
    GAIPerceptionCounts = FAIPerceptionCounts();
    GAIPerceptionBlueprintCandidates = 0;
    GAIPerceptionScopedBlueprintCandidates = 0;
    GAIPerceptionLoadedBlueprints = 0;
    GAIPerceptionGeneratedClasses = 0;
    GAIPerceptionScannedBlueprints = 0;

    const FString OutputDir = SmartObjectSystemsOutputDir();
    if (!GAIPerceptionWriters.Open(OutputDir))
    {
        OutError = TEXT("could not create AI Perception systems JSONL output files");
        GAIPerceptionWriters = FAIPerceptionWriters();
        return false;
    }

    const bool bAIPerceptionOk = ScanAIPerceptionProjectModelExactLoad(
        Assets,
        ProjectDir,
        bIncludeEngine,
        bIncludeSelf,
        ToolPluginDir,
        OutError);

    // These specialist streams are separate from the legacy driver writer group.
    // Destroy the writers synchronously before the authoritative manifest write.
    GAIPerceptionWriters = FAIPerceptionWriters();
    if (!bAIPerceptionOk)
    {
        return false;
    }

    return ScanGASAndSmartObjectProjectModels(
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

static bool UpgradeSystemsManifestToSchema8(const FString& ManifestPath)
{
    FString Text;
    if (!FFileHelper::LoadFileToString(Text, *ManifestPath))
    {
        return false;
    }

    TSharedPtr<FJsonObject> Root;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
    if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
    {
        return false;
    }

    Root->SetNumberField(TEXT("schema_version"), 8);

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
    Counts->SetNumberField(TEXT("ai_perception_blueprint_candidates"), GAIPerceptionBlueprintCandidates);
    Counts->SetNumberField(TEXT("ai_perception_scoped_blueprint_candidates"), GAIPerceptionScopedBlueprintCandidates);
    Counts->SetNumberField(TEXT("ai_perception_loaded_blueprints"), GAIPerceptionLoadedBlueprints);
    Counts->SetNumberField(TEXT("ai_perception_generated_classes"), GAIPerceptionGeneratedClasses);
    Counts->SetNumberField(TEXT("ai_perception_scanned_blueprints"), GAIPerceptionScannedBlueprints);
    Counts->SetNumberField(TEXT("ai_perception_components"), GAIPerceptionCounts.Components);
    Counts->SetNumberField(TEXT("ai_perception_sense_configs"), GAIPerceptionCounts.SenseConfigs);
    Counts->SetNumberField(TEXT("ai_perception_stimuli_sources"), GAIPerceptionCounts.StimuliSources);
    Counts->SetNumberField(TEXT("ai_perception_registered_senses"), GAIPerceptionCounts.RegisteredSenses);
    Counts->SetNumberField(TEXT("ai_perception_properties"), GAIPerceptionCounts.Properties);
    Counts->SetNumberField(TEXT("ai_perception_truncated_properties"), GAIPerceptionCounts.TruncatedProperties);
    Counts->SetNumberField(TEXT("ai_perception_property_depth_limit_hits"), GAIPerceptionCounts.PropertyDepthLimitHits);
    Counts->SetNumberField(TEXT("ai_perception_property_row_limit_hits"), GAIPerceptionCounts.PropertyRowLimitHits);
    Counts->SetNumberField(TEXT("ai_perception_container_element_limit_hits"), GAIPerceptionCounts.ContainerElementLimitHits);

    TArray<TSharedPtr<FJsonValue>> Files;
    const TArray<TSharedPtr<FJsonValue>>* ExistingFiles = nullptr;
    if (Root->TryGetArrayField(TEXT("files"), ExistingFiles) && ExistingFiles)
    {
        Files = *ExistingFiles;
    }
    TSet<FString> ExistingNames;
    for (const TSharedPtr<FJsonValue>& Value : Files)
    {
        FString Name;
        if (Value.IsValid() && Value->TryGetString(Name))
        {
            ExistingNames.Add(Name);
        }
    }
    static const TCHAR* AIPerceptionFiles[] = {
        TEXT("ai_perception_components.jsonl"),
        TEXT("ai_perception_sense_configs.jsonl"),
        TEXT("ai_perception_stimuli_sources.jsonl"),
        TEXT("ai_perception_registered_senses.jsonl"),
        TEXT("ai_perception_properties.jsonl")
    };
    for (const TCHAR* Name : AIPerceptionFiles)
    {
        if (!ExistingNames.Contains(Name))
        {
            Files.Add(MakeShared<FJsonValueString>(Name));
        }
    }
    Root->SetArrayField(TEXT("files"), Files);

    FString Updated;
    const TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer =
        TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Updated);
    if (!FJsonSerializer::Serialize(Root.ToSharedRef(), Writer))
    {
        return false;
    }
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
        TEXT("UnrealAssetToolSystems: synchronously promoted systems manifest to schema 8 ai_perception candidates=%lld scoped=%lld loaded_blueprints=%lld generated_classes=%lld scanned_blueprints=%lld components=%lld configs=%lld stimuli_sources=%lld registered_senses=%lld properties=%lld truncated=%lld depth_limit_hits=%lld row_limit_hits=%lld container_limit_hits=%lld"),
        GAIPerceptionBlueprintCandidates,
        GAIPerceptionScopedBlueprintCandidates,
        GAIPerceptionLoadedBlueprints,
        GAIPerceptionGeneratedClasses,
        GAIPerceptionScannedBlueprints,
        GAIPerceptionCounts.Components,
        GAIPerceptionCounts.SenseConfigs,
        GAIPerceptionCounts.StimuliSources,
        GAIPerceptionCounts.RegisteredSenses,
        GAIPerceptionCounts.Properties,
        GAIPerceptionCounts.TruncatedProperties,
        GAIPerceptionCounts.PropertyDepthLimitHits,
        GAIPerceptionCounts.PropertyRowLimitHits,
        GAIPerceptionCounts.ContainerElementLimitHits);
    return true;
}

struct FAIPerceptionSystemsFileHelperProxy
{
    using EEncodingOptions = FFileHelper::EEncodingOptions;

    static bool SaveStringToFile(
        const FString& String,
        const TCHAR* Filename,
        EEncodingOptions EncodingOptions)
    {
        if (!FSmartObjectSystemsFileHelperProxy::SaveStringToFile(String, Filename, EncodingOptions))
        {
            return false;
        }

        const FString Path = Filename ? FString(Filename) : FString();
        if (!FPaths::GetCleanFilename(Path).Equals(TEXT("systems_manifest.json"), ESearchCase::IgnoreCase))
        {
            return true;
        }
        return UpgradeSystemsManifestToSchema8(Path);
    }
};

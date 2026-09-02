static FString SmartObjectSystemsOutputDir()
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
    return NormalizeAbsolutePath(OutputDir);
}

static bool ScanGASAndSmartObjectProjectModels(
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
    GSmartObjectCounts = FSmartObjectCounts();

    const FString OutputDir = SmartObjectSystemsOutputDir();
    if (!GSmartObjectWriters.Open(OutputDir))
    {
        OutError = TEXT("could not create Smart Object systems JSONL output files");
        GSmartObjectWriters = FSmartObjectWriters();
        return false;
    }

    const bool bSmartObjectsOk = ScanSmartObjectProjectModel(
        Assets,
        ProjectDir,
        bIncludeEngine,
        bIncludeSelf,
        ToolPluginDir,
        Writers,
        Counts,
        SeenStateOwners,
        OutError);

    // Smart Object streams are not owned by the legacy driver writer group.
    // Finalize them synchronously before the driver publishes its manifest.
    GSmartObjectWriters = FSmartObjectWriters();
    if (!bSmartObjectsOk)
    {
        return false;
    }

    return ScanGASProjectModelPolicy(
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

static bool UpgradeSystemsManifestToSchema7(const FString& ManifestPath)
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

    Root->SetNumberField(TEXT("schema_version"), 7);

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
    Counts->SetNumberField(TEXT("smartobject_definitions"), GSmartObjectCounts.Definitions);
    Counts->SetNumberField(TEXT("smartobject_slots"), GSmartObjectCounts.Slots);
    Counts->SetNumberField(TEXT("smartobject_behaviors"), GSmartObjectCounts.Behaviors);
    Counts->SetNumberField(TEXT("smartobject_behavior_properties"), GSmartObjectCounts.BehaviorProperties);

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
    static const TCHAR* SmartObjectFiles[] = {
        TEXT("smartobject_definitions.jsonl"),
        TEXT("smartobject_slots.jsonl"),
        TEXT("smartobject_behaviors.jsonl"),
        TEXT("smartobject_behavior_properties.jsonl")
    };
    for (const TCHAR* Name : SmartObjectFiles)
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
        TEXT("UnrealAssetToolSystems: synchronously promoted systems manifest to schema 7 smartobjects definitions=%lld slots=%lld behaviors=%lld behavior_properties=%lld"),
        GSmartObjectCounts.Definitions,
        GSmartObjectCounts.Slots,
        GSmartObjectCounts.Behaviors,
        GSmartObjectCounts.BehaviorProperties);
    return true;
}

// The shared systems driver owns the authoritative SaveSystemsManifest()
// implementation. While that single include is compiled, UnrealAssetToolSystemsScanner.cpp
// aliases FFileHelper to this proxy. The proxy performs the driver's real file
// write first, then upgrades that exact completed manifest before
// SaveSystemsManifest() returns. No delegate ordering or shutdown behavior is
// part of the schema-7 correctness path.
struct FSmartObjectSystemsFileHelperProxy
{
    using EEncodingOptions = FFileHelper::EEncodingOptions;

    static bool SaveStringToFile(
        const FString& String,
        const TCHAR* Filename,
        EEncodingOptions EncodingOptions)
    {
        if (!FFileHelper::SaveStringToFile(String, Filename, EncodingOptions))
        {
            return false;
        }

        const FString Path = Filename ? FString(Filename) : FString();
        if (!FPaths::GetCleanFilename(Path).Equals(TEXT("systems_manifest.json"), ESearchCase::IgnoreCase))
        {
            return true;
        }
        return UpgradeSystemsManifestToSchema7(Path);
    }
};

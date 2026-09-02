static bool GSystemsOnlyWriterBuffersFinalized = false;

static void FinalizeSystemsOnlyWriterBuffers()
{
    if (!FParse::Param(FCommandLine::Get(), TEXT("UnrealAssetToolSystemsOnly")) ||
        GSystemsOnlyWriterBuffersFinalized)
    {
        return;
    }

    // Specialized writer groups are static because their extraction helpers are
    // spread across included implementation files. Systems-only mode requests
    // exit immediately after RunSystemsScan() returns. Do not depend on module
    // static destruction to flush the final JSONL tail; finalize during the
    // engine's explicit pre-exit phase as a fallback to the normal success path.
    GMoverWriters = FMoverWriters();
    GGameplayCameraWriters = FGameplayCameraWriters();
    GMassZoneGraphWriters = FMassZoneGraphWriters();
    GGASWriters = FGASWriters();
    GSystemsOnlyWriterBuffersFinalized = true;

    UE_LOG(LogTemp, Display, TEXT("UnrealAssetToolSystems: finalized specialized JSONL writer buffers before engine exit"));
}

struct FSystemsFinalizeBootstrap
{
    FSystemsFinalizeBootstrap()
    {
        FCoreDelegates::OnEnginePreExit.AddStatic(&FinalizeSystemsOnlyWriterBuffers);
    }
};

static FSystemsFinalizeBootstrap GSystemsFinalizeBootstrap;

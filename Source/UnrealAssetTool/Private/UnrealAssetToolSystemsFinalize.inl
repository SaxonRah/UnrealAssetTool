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
        // This bootstrap is defined after UnrealAssetToolSystemsDriver.inl in
        // the same translation unit. The driver's FSystemsScannerBootstrap is
        // therefore constructed first and registers OnPostEngineInit first.
        // During the single post-engine-init broadcast RunSystemsScan() writes
        // the schema-6 base manifest, returns, and only then this callback
        // promotes that completed manifest to schema 7. This is synchronous and
        // does not depend on RequestExit/pre-exit delegate behavior.
        FCoreDelegates::GetOnPostEngineInit().AddStatic(&FinalizeSmartObjectSchema7Manifest);

        // Keep the existing writer-buffer cleanup as a defensive exit fallback.
        FCoreDelegates::OnEnginePreExit.AddStatic(&FinalizeSystemsOnlyWriterBuffers);
    }
};

static FSystemsFinalizeBootstrap GSystemsFinalizeBootstrap;

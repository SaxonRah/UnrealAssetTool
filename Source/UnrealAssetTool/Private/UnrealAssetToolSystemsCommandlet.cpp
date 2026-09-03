#include "UnrealAssetToolSystemsCommandlet.h"

#include "UnrealAssetToolSystemsScanner.h"

UUnrealAssetToolSystemsCommandlet::UUnrealAssetToolSystemsCommandlet()
{
    IsClient = false;
    IsServer = false;
    IsEditor = true;
    LogToConsole = true;
    ShowErrorCount = true;
}

int32 UUnrealAssetToolSystemsCommandlet::Main(const FString& Params)
{
    (void)Params;
    FString Error;
    if (!UnrealAssetToolSystems::RunSystemsScanForCommandlet(Error))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolSystems commandlet: %s"), *Error);
        return 3;
    }
    return 0;
}

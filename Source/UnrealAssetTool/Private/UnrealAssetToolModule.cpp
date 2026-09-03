#include "UnrealAssetToolAnimationMeshPhysicsScanner.h"
#include "UnrealAssetToolStaticMeshCommandlet.h"

#include "Misc/CommandLine.h"
#include "Misc/CoreDelegates.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "UObject/UObjectGlobals.h"

namespace
{
bool IsWorldCommandlet()
{
    FString RunCommandlet;
    FParse::Value(FCommandLine::Get(), TEXT("run="), RunCommandlet);
    return RunCommandlet.Equals(TEXT("UnrealAssetToolWorld"), ESearchCase::IgnoreCase);
}

FString ScanOutputDir()
{
    FString OutputDir;
    FParse::Value(FCommandLine::Get(), TEXT("Output="), OutputDir);
    return OutputDir;
}

void RunAnimationMeshPhysicsPass(const FString& OutputDir)
{
    FString Error;
    if (!UnrealAssetToolAnimationMeshPhysics::RunScan(OutputDir, Error))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolAnimationMeshPhysics: %s"), *Error);
    }
}

void RunStaticMeshPass(const FString& OutputDir)
{
    if (OutputDir.IsEmpty())
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolStaticMesh: World commandlet did not provide -Output"));
        return;
    }

    const FString CaptureDir = FPaths::Combine(OutputDir, TEXT("staticmesh-native-capture"));
    UUnrealAssetToolStaticMeshCommandlet* Commandlet = NewObject<UUnrealAssetToolStaticMeshCommandlet>();
    if (!Commandlet)
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolStaticMesh: could not allocate compact scan commandlet"));
        return;
    }

    const FString Params = FString::Printf(TEXT("-Output=\"%s\""), *CaptureDir);
    const int32 Result = Commandlet->Main(Params);
    if (Result != 0)
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolStaticMesh compact World-pass capture failed with exit code %d"), Result);
    }
}

void RunCanonicalSpecialistPasses()
{
    if (!IsWorldCommandlet())
    {
        return;
    }

    const FString OutputDir = ScanOutputDir();
    RunAnimationMeshPhysicsPass(OutputDir);
    RunStaticMeshPass(OutputDir);
}
}

class FUnrealAssetToolModule final : public IModuleInterface
{
public:
    virtual void StartupModule() override
    {
        UE_LOG(LogTemp, Display, TEXT("UnrealAssetTool: editor module loaded."));
        FCoreDelegates::GetOnPostEngineInit().AddStatic(&RunCanonicalSpecialistPasses);
    }
};

IMPLEMENT_MODULE(FUnrealAssetToolModule, UnrealAssetTool)

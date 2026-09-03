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

void RunAnimationMeshPhysicsPass()
{
    FString RunCommandlet;
    FParse::Value(FCommandLine::Get(), TEXT("run="), RunCommandlet);
    if (!RunCommandlet.Equals(TEXT("UnrealAssetToolWorld"), ESearchCase::IgnoreCase))
    {
        return;
    }

    FString OutputDir;
    FParse::Value(FCommandLine::Get(), TEXT("Output="), OutputDir);

    FString Error;
    if (!UnrealAssetToolAnimationMeshPhysics::RunScan(OutputDir, Error))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolAnimationMeshPhysics: %s"), *Error);
    }

    // StaticMesh uses the same already-running headless World commandlet so the
    // normal scan gains authored mesh topology without another Editor startup.
    RunStaticMeshPass(OutputDir);
}
}

class FUnrealAssetToolModule final : public IModuleInterface
{
public:
    virtual void StartupModule() override
    {
        UE_LOG(LogTemp, Display, TEXT("UnrealAssetTool: editor module loaded."));
        FCoreDelegates::GetOnPostEngineInit().AddStatic(&RunAnimationMeshPhysicsPass);
    }
};

IMPLEMENT_MODULE(FUnrealAssetToolModule, UnrealAssetTool)

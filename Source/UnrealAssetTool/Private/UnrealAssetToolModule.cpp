#include "UnrealAssetToolAnimationMeshPhysicsScanner.h"
#include "UnrealAssetToolMotionWarpingCommandlet.h"
#include "UnrealAssetToolStaticMeshCommandlet.h"
#include "UnrealAssetToolWorldGeometryCommandlet.h"
#include "UnrealAssetToolWorldGeometryFoliageCommandlet.h"

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

void RunWorldGeometryPass(const FString& OutputDir)
{
    if (OutputDir.IsEmpty())
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolWorldGeometry: World commandlet did not provide -Output"));
        return;
    }

    const FString CaptureDir = FPaths::Combine(OutputDir, TEXT("world-geometry-native-capture"));
    const FString Params = FString::Printf(TEXT("-Output=\"%s\""), *CaptureDir);

    UUnrealAssetToolWorldGeometryCommandlet* GeometryCommandlet =
        NewObject<UUnrealAssetToolWorldGeometryCommandlet>();
    if (!GeometryCommandlet)
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolWorldGeometry: could not allocate authored geometry commandlet"));
        return;
    }

    const int32 GeometryResult = GeometryCommandlet->Main(Params);
    if (GeometryResult != 0)
    {
        UE_LOG(
            LogTemp,
            Error,
            TEXT("UnrealAssetToolWorldGeometry compact World-pass capture failed with exit code %d"),
            GeometryResult);
        return;
    }

    // AInstancedFoliageActor keeps FoliageInfos as protected native state in UE
    // 5.8. The refinement reads only the public editor-authoring API
    // (ForEachFoliageInfo + FFoliageInfo::Instances) into the same raw capture.
    // It deliberately does not read HISM render-instance data or runtime state.
    UUnrealAssetToolWorldGeometryFoliageCommandlet* FoliageCommandlet =
        NewObject<UUnrealAssetToolWorldGeometryFoliageCommandlet>();
    if (!FoliageCommandlet)
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolWorldGeometry: could not allocate native foliage refinement commandlet"));
        return;
    }

    const int32 FoliageResult = FoliageCommandlet->Main(Params);
    if (FoliageResult != 0)
    {
        UE_LOG(
            LogTemp,
            Error,
            TEXT("UnrealAssetToolWorldGeometry native foliage World-pass refinement failed with exit code %d"),
            FoliageResult);
    }
}

void RunMotionWarpingPass(const FString& OutputDir)
{
    if (OutputDir.IsEmpty())
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolMotionWarping: World commandlet did not provide -Output"));
        return;
    }

    const FString CaptureDir = FPaths::Combine(OutputDir, TEXT("motion-warping-native-capture"));
    UUnrealAssetToolMotionWarpingCommandlet* Commandlet =
        NewObject<UUnrealAssetToolMotionWarpingCommandlet>();
    if (!Commandlet)
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolMotionWarping: could not allocate authored capture commandlet"));
        return;
    }

    const FString Params = FString::Printf(TEXT("-Output=\"%s\""), *CaptureDir);
    const int32 Result = Commandlet->Main(Params);
    if (Result != 0)
    {
        UE_LOG(
            LogTemp,
            Error,
            TEXT("UnrealAssetToolMotionWarping compact World-pass capture failed with exit code %d"),
            Result);
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

    // Reuse this already-running headless World commandlet for specialist native
    // authored passes; neither pass launches another editor or loads a map.
    RunStaticMeshPass(OutputDir);
    RunWorldGeometryPass(OutputDir);
    RunMotionWarpingPass(OutputDir);
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

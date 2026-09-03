#include "UnrealAssetToolAnimationMeshPhysicsScanner.h"

#include "Misc/CommandLine.h"
#include "Misc/CoreDelegates.h"
#include "Misc/Parse.h"
#include "Modules/ModuleManager.h"

namespace
{
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

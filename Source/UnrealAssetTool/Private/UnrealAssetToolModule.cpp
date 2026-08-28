#include "Modules/ModuleManager.h"

class FUnrealAssetToolModule final : public IModuleInterface
{
public:
    virtual void StartupModule() override
    {
        UE_LOG(LogTemp, Display, TEXT("UnrealAssetTool: editor module loaded."));
    }
};

IMPLEMENT_MODULE(FUnrealAssetToolModule, UnrealAssetTool)

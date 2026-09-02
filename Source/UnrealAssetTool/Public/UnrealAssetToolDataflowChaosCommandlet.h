#pragma once

#include "Commandlets/Commandlet.h"
#include "UnrealAssetToolDataflowChaosCommandlet.generated.h"

UCLASS()
class UNREALASSETTOOL_API UUnrealAssetToolDataflowChaosCommandlet : public UCommandlet
{
    GENERATED_BODY()

public:
    UUnrealAssetToolDataflowChaosCommandlet();
    virtual int32 Main(const FString& Params) override;
};

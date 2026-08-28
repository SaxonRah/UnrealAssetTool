#pragma once

#include "Commandlets/Commandlet.h"
#include "UnrealAssetToolCommandlet.generated.h"

UCLASS()
class UNREALASSETTOOL_API UUnrealAssetToolCommandlet final : public UCommandlet
{
    GENERATED_BODY()

public:
    UUnrealAssetToolCommandlet();
    virtual int32 Main(const FString& Params) override;
};

#pragma once

#include "Commandlets/Commandlet.h"
#include "UnrealAssetToolGASCommandlet.generated.h"

UCLASS()
class UNREALASSETTOOL_API UUnrealAssetToolGASCommandlet : public UCommandlet
{
    GENERATED_BODY()
public:
    UUnrealAssetToolGASCommandlet();
    virtual int32 Main(const FString& Params) override;
};

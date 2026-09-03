#pragma once

#include "Commandlets/Commandlet.h"
#include "UnrealAssetToolSystemsCommandlet.generated.h"

UCLASS()
class UNREALASSETTOOL_API UUnrealAssetToolSystemsCommandlet : public UCommandlet
{
    GENERATED_BODY()

public:
    UUnrealAssetToolSystemsCommandlet();
    virtual int32 Main(const FString& Params) override;
};

#pragma once

#include "Commandlets/Commandlet.h"
#include "UnrealAssetToolAIPerceptionCommandlet.generated.h"

UCLASS()
class UNREALASSETTOOL_API UUnrealAssetToolAIPerceptionCommandlet : public UCommandlet
{
    GENERATED_BODY()
public:
    UUnrealAssetToolAIPerceptionCommandlet();
    virtual int32 Main(const FString& Params) override;
};

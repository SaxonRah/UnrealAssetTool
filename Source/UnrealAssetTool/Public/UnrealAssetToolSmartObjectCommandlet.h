#pragma once

#include "Commandlets/Commandlet.h"
#include "UnrealAssetToolSmartObjectCommandlet.generated.h"

UCLASS()
class UNREALASSETTOOL_API UUnrealAssetToolSmartObjectCommandlet : public UCommandlet
{
    GENERATED_BODY()
public:
    UUnrealAssetToolSmartObjectCommandlet();
    virtual int32 Main(const FString& Params) override;
};

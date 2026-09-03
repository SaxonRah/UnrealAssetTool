#pragma once

#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "UnrealAssetToolUAFCommandlet.generated.h"

UCLASS()
class UNREALASSETTOOL_API UUnrealAssetToolUAFCommandlet : public UCommandlet
{
    GENERATED_BODY()

public:
    UUnrealAssetToolUAFCommandlet();
    virtual int32 Main(const FString& Params) override;
};

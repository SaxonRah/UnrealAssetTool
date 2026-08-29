#pragma once

#include "Commandlets/Commandlet.h"
#include "UnrealAssetToolWorldCommandlet.generated.h"

/**
 * Experimental scanner-schema-12 world pass.
 *
 * This is intentionally a separate commandlet while world/map loading and
 * World Partition descriptor traversal are being validated. It writes only
 * world facts and does not mutate the frozen schema-11 structural outputs.
 */
UCLASS()
class UNREALASSETTOOL_API UUnrealAssetToolWorldCommandlet : public UCommandlet
{
    GENERATED_BODY()

public:
    UUnrealAssetToolWorldCommandlet();

    virtual int32 Main(const FString& Params) override;
};

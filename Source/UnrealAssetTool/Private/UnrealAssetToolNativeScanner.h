#pragma once

#include "CoreMinimal.h"

namespace UnrealAssetToolNative
{
    constexpr int32 SchemaVersion = 1;

    bool Scan(
        const FString& ProjectDir,
        const FString& ToolPluginDir,
        const FString& OutputDir,
        FString& OutError);
}

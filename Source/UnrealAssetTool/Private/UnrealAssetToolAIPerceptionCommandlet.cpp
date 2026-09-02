#include "UnrealAssetToolAIPerceptionCommandlet.h"

#include "Engine/Blueprint.h"
#include "HAL/FileManager.h"
#include "Json.h"
#include "Misc/App.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/Package.h"
#include "UObject/SoftObjectPtr.h"
#include "UObject/UObjectGlobals.h"
#include "UObject/UObjectHash.h"
#include "UObject/UnrealType.h"

namespace UnrealAssetToolAIPerception
{
constexpr int32 SchemaVersion = 1;
constexpr int32 MaxExportChars = 65536;
constexpr int32 MaxPropertyDepth = 16;
constexpr int32 MaxElementsPerContainer = 4096;
constexpr int32 MaxPropertyRowsPerObject = 65536;
constexpr int32 MaxObjectsPerAsset = 4096;

struct FCounts
{
    int64 FocusAssets = 0;
    int64 LoadedAssets = 0;
    int64 BlueprintAssets = 0;
    int64 PerceptionComponents = 0;
    int64 StimuliSourceComponents = 0;
    int64 SenseConfigs = 0;
    int64 Objects = 0;
    int64 Properties = 0;
    int64 References = 0;
    int64 TruncatedProperties = 0;
    int64 PropertyDepthLimitHits = 0;
    int64 PropertyRowLimitHits = 0;
    int64 ContainerElementLimitHits = 0;
};

class FJsonlWriter
{
public:
    bool Open(const FString& Filename)
    {
        IFileManager::Get().MakeDirectory(*FPaths::GetPath(Filename), true);
        Archive.Reset(IFileManager::Get().CreateFileWriter(*Filename));
        return Archive.IsValid();
    }

    bool Write(const TSharedRef<FJsonObject>& Object)
    {
        if (!Archive.IsValid()) return false;
        FString Line;
        const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
            TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Line);
        if (!FJsonSerializer::Serialize(Object, Writer)) return false;
        Line.AppendChar(TEXT('\n'));
        FTCHARToUTF8 Utf8(*Line);
        Archive->Serialize((void*)Utf8.Get(), Utf8.Length());
        return !Archive->IsError();
    }

    bool Close()
    {
        if (!Archive.IsValid()) return true;
        const bool bClosed = Archive->Close();
        const bool bOk = bClosed && !Archive->IsError();
        Archive.Reset();
        return bOk;
    }

    ~FJsonlWriter() { Close(); }

private:
    TUniquePtr<FArchive> Archive;
};

struct FWriters
{
    FJsonlWriter Assets;
    FJsonlWriter Objects;
    FJsonlWriter Properties;
    FJsonlWriter References;

    bool Open(const FString& OutputDir)
    {
        return Assets.Open(FPaths::Combine(OutputDir, TEXT("ai_perception_assets.jsonl"))) &&
            Objects.Open(FPaths::Combine(OutputDir, TEXT("ai_perception_objects.jsonl"))) &&
            Properties.Open(FPaths::Combine(OutputDir, TEXT("ai_perception_properties.jsonl"))) &&
            References.Open(FPaths::Combine(OutputDir, TEXT("ai_perception_references.jsonl")));
    }

    bool Close()
    {
        const bool A = Assets.Close();
        const bool B = Objects.Close();
        const bool C = Properties.Close();
        const bool D = References.Close();
        return A && B && C && D;
    }
};

static bool ShouldInspectProperty(const FProperty* Property)
{
    if (!Property) return false;
    constexpr EPropertyFlags Rejected =
        CPF_Transient | CPF_DuplicateTransient | CPF_NonPIEDuplicateTransient |
        CPF_Deprecated | CPF_SkipSerialization;
    return !Property->HasAnyPropertyFlags(Rejected);
}

static bool ClassInheritsName(const UClass* Class, const TCHAR* BaseName)
{
    for (const UClass* It = Class; It; It = It->GetSuperClass())
    {
        if (It->GetName().Equals(BaseName, ESearchCase::CaseSensitive)) return true;
    }
    return false;
}

static FString ObjectKind(UObject* Object)
{
    if (!Object) return FString();
    const UClass* Class = Object->GetClass();
    if (ClassInheritsName(Class, TEXT("AIPerceptionStimuliSourceComponent")))
    {
        return TEXT("stimuli_source_component_template");
    }
    if (ClassInheritsName(Class, TEXT("AIPerceptionComponent")))
    {
        return TEXT("perception_component_template");
    }
    if (ClassInheritsName(Class, TEXT("AISenseConfig")))
    {
        return TEXT("sense_config");
    }
    return FString();
}

static FString ExportProperty(
    const FProperty* Property,
    const void* ValuePtr,
    UObject* Owner,
    bool& bTruncated)
{
    bTruncated = false;
    if (!Property || !ValuePtr) return FString();
    FString Text;
    Property->ExportTextItem_Direct(Text, ValuePtr, nullptr, Owner, PPF_None, nullptr);
    if (Text.Len() > MaxExportChars)
    {
        Text.LeftInline(MaxExportChars, EAllowShrinking::No);
        bTruncated = true;
    }
    return Text;
}

static FString ContainerKind(const FProperty* Property)
{
    if (CastField<FArrayProperty>(Property)) return TEXT("array");
    if (CastField<FSetProperty>(Property)) return TEXT("set");
    if (CastField<FMapProperty>(Property)) return TEXT("map");
    if (CastField<FStructProperty>(Property)) return TEXT("struct");
    if (CastField<FSoftObjectProperty>(Property)) return TEXT("soft_object");
    if (CastField<FObjectPropertyBase>(Property)) return TEXT("object");
    return TEXT("scalar");
}

struct FWalkContext
{
    FString SourcePath;
    FString OwnerPath;
    FString OwnerKind;
    FString OwnerClass;
    UObject* OwnerObject = nullptr;
    UObject* DefaultObject = nullptr;
    FWriters* Writers = nullptr;
    FCounts* Counts = nullptr;
    int32 Rows = 0;
    bool bFailed = false;
};

static void EmitReference(
    FWalkContext& Context,
    const FString& RootProperty,
    const FString& PropertyPath,
    const FString& ReferenceKind,
    const FString& TargetPath,
    const FString& TargetClass)
{
    if (!Context.Writers || !Context.Counts || TargetPath.IsEmpty() || Context.bFailed) return;
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("source_path"), Context.SourcePath);
    Row->SetStringField(TEXT("owner_path"), Context.OwnerPath);
    Row->SetStringField(TEXT("owner_kind"), Context.OwnerKind);
    Row->SetStringField(TEXT("owner_class"), Context.OwnerClass);
    Row->SetStringField(TEXT("root_property"), RootProperty);
    Row->SetStringField(TEXT("property_path"), PropertyPath);
    Row->SetStringField(TEXT("reference_kind"), ReferenceKind);
    Row->SetStringField(TEXT("target_path"), TargetPath);
    Row->SetStringField(TEXT("target_class"), TargetClass);
    if (!Context.Writers->References.Write(Row))
    {
        Context.bFailed = true;
        return;
    }
    ++Context.Counts->References;
}

static void EmitProperty(
    const FProperty* Property,
    const void* ValuePtr,
    const void* DefaultValuePtr,
    const FString& RootProperty,
    const FString& PropertyPath,
    int32 Depth,
    int32 ElementCount,
    FWalkContext& Context)
{
    if (!Context.Writers || !Context.Counts || !Property || Context.bFailed) return;
    if (Context.Rows >= MaxPropertyRowsPerObject)
    {
        ++Context.Counts->PropertyRowLimitHits;
        return;
    }

    bool bTruncated = false;
    const FString Value = ExportProperty(Property, ValuePtr, Context.OwnerObject, bTruncated);
    bool bDefaultTruncated = false;
    const FString DefaultValue = DefaultValuePtr
        ? ExportProperty(Property, DefaultValuePtr, Context.DefaultObject, bDefaultTruncated)
        : FString();
    const bool bDiffers = !DefaultValuePtr || !Property->Identical(ValuePtr, DefaultValuePtr, PPF_None);

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("source_path"), Context.SourcePath);
    Row->SetStringField(TEXT("owner_path"), Context.OwnerPath);
    Row->SetStringField(TEXT("owner_kind"), Context.OwnerKind);
    Row->SetStringField(TEXT("owner_class"), Context.OwnerClass);
    Row->SetStringField(TEXT("declaring_type"),
        Property->GetOwnerStruct() ? Property->GetOwnerStruct()->GetPathName() : FString());
    Row->SetStringField(TEXT("root_property"), RootProperty);
    Row->SetStringField(TEXT("property_name"), Property->GetName());
    Row->SetStringField(TEXT("property_path"), PropertyPath);
    Row->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
    Row->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
    Row->SetStringField(TEXT("container_kind"), ContainerKind(Property));
    Row->SetNumberField(TEXT("depth"), Depth);
    if (ElementCount >= 0) Row->SetNumberField(TEXT("element_count"), ElementCount);
    Row->SetStringField(TEXT("value"), Value);
    Row->SetStringField(TEXT("class_default_value"), DefaultValue);
    Row->SetBoolField(TEXT("class_default_present"), DefaultValuePtr != nullptr);
    Row->SetBoolField(TEXT("differs_from_class_default"), bDiffers);
    Row->SetBoolField(TEXT("truncated"), bTruncated || bDefaultTruncated);
    if (!Context.Writers->Properties.Write(Row))
    {
        Context.bFailed = true;
        return;
    }
    ++Context.Rows;
    ++Context.Counts->Properties;
    if (bTruncated || bDefaultTruncated) ++Context.Counts->TruncatedProperties;
}

static void WalkPropertyValue(
    const FProperty* Property,
    const void* ValuePtr,
    const void* DefaultValuePtr,
    const FString& RootProperty,
    const FString& PropertyPath,
    int32 Depth,
    FWalkContext& Context)
{
    if (!Property || !ValuePtr || Context.bFailed) return;
    if (Depth > MaxPropertyDepth)
    {
        ++Context.Counts->PropertyDepthLimitHits;
        return;
    }
    if (Context.Rows >= MaxPropertyRowsPerObject)
    {
        ++Context.Counts->PropertyRowLimitHits;
        return;
    }

    if (const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
    {
        FScriptArrayHelper Helper(ArrayProperty, ValuePtr);
        EmitProperty(Property, ValuePtr, DefaultValuePtr, RootProperty, PropertyPath, Depth, Helper.Num(), Context);
        FScriptArrayHelper* DefaultHelper = nullptr;
        TUniquePtr<FScriptArrayHelper> DefaultHolder;
        if (DefaultValuePtr)
        {
            DefaultHolder = MakeUnique<FScriptArrayHelper>(ArrayProperty, DefaultValuePtr);
            DefaultHelper = DefaultHolder.Get();
        }
        const int32 Limit = FMath::Min(Helper.Num(), MaxElementsPerContainer);
        if (Helper.Num() > Limit) ++Context.Counts->ContainerElementLimitHits;
        for (int32 Index = 0; Index < Limit && !Context.bFailed; ++Index)
        {
            const void* ChildDefault =
                DefaultHelper && Index < DefaultHelper->Num() ? DefaultHelper->GetRawPtr(Index) : nullptr;
            WalkPropertyValue(
                ArrayProperty->Inner,
                Helper.GetRawPtr(Index),
                ChildDefault,
                RootProperty,
                FString::Printf(TEXT("%s[%d]"), *PropertyPath, Index),
                Depth + 1,
                Context);
        }
        return;
    }

    if (const FSetProperty* SetProperty = CastField<FSetProperty>(Property))
    {
        FScriptSetHelper Helper(SetProperty, ValuePtr);
        EmitProperty(Property, ValuePtr, DefaultValuePtr, RootProperty, PropertyPath, Depth, Helper.Num(), Context);
        int32 Emitted = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && Emitted < MaxElementsPerContainer && !Context.bFailed; ++Index)
        {
            if (!Helper.IsValidIndex(Index)) continue;
            WalkPropertyValue(
                SetProperty->ElementProp,
                Helper.GetElementPtr(Index),
                nullptr,
                RootProperty,
                FString::Printf(TEXT("%s{%d}"), *PropertyPath, Emitted++),
                Depth + 1,
                Context);
        }
        if (Helper.Num() > Emitted) ++Context.Counts->ContainerElementLimitHits;
        return;
    }

    if (const FMapProperty* MapProperty = CastField<FMapProperty>(Property))
    {
        FScriptMapHelper Helper(MapProperty, ValuePtr);
        EmitProperty(Property, ValuePtr, DefaultValuePtr, RootProperty, PropertyPath, Depth, Helper.Num(), Context);
        int32 Emitted = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && Emitted < MaxElementsPerContainer && !Context.bFailed; ++Index)
        {
            if (!Helper.IsValidIndex(Index)) continue;
            const FString Base = FString::Printf(TEXT("%s{%d}"), *PropertyPath, Emitted++);
            WalkPropertyValue(MapProperty->KeyProp, Helper.GetKeyPtr(Index), nullptr, RootProperty, Base + TEXT(".key"), Depth + 1, Context);
            WalkPropertyValue(MapProperty->ValueProp, Helper.GetValuePtr(Index), nullptr, RootProperty, Base + TEXT(".value"), Depth + 1, Context);
        }
        if (Helper.Num() > Emitted) ++Context.Counts->ContainerElementLimitHits;
        return;
    }

    if (const FStructProperty* StructProperty = CastField<FStructProperty>(Property))
    {
        EmitProperty(Property, ValuePtr, DefaultValuePtr, RootProperty, PropertyPath, Depth, -1, Context);
        if (!StructProperty->Struct) return;
        for (TFieldIterator<FProperty> It(StructProperty->Struct); It && !Context.bFailed; ++It)
        {
            const FProperty* Inner = *It;
            if (!ShouldInspectProperty(Inner)) continue;
            for (int32 StaticIndex = 0; StaticIndex < Inner->ArrayDim && !Context.bFailed; ++StaticIndex)
            {
                const void* InnerValue = Inner->ContainerPtrToValuePtr<void>(ValuePtr, StaticIndex);
                const void* InnerDefault = DefaultValuePtr
                    ? Inner->ContainerPtrToValuePtr<void>(DefaultValuePtr, StaticIndex)
                    : nullptr;
                const FString ChildPath = PropertyPath + TEXT(".") + Inner->GetName() +
                    (Inner->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
                WalkPropertyValue(Inner, InnerValue, InnerDefault, RootProperty, ChildPath, Depth + 1, Context);
            }
        }
        return;
    }

    EmitProperty(Property, ValuePtr, DefaultValuePtr, RootProperty, PropertyPath, Depth, -1, Context);

    if (const FSoftObjectProperty* SoftProperty = CastField<FSoftObjectProperty>(Property))
    {
        const FSoftObjectPtr* SoftPtr = static_cast<const FSoftObjectPtr*>(ValuePtr);
        if (SoftPtr && !SoftPtr->IsNull())
        {
            EmitReference(Context, RootProperty, PropertyPath, TEXT("soft_object"), SoftPtr->ToSoftObjectPath().ToString(), FString());
        }
        return;
    }

    if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
    {
        UObject* Target = ObjectProperty->GetObjectPropertyValue(ValuePtr);
        if (Target)
        {
            EmitReference(
                Context,
                RootProperty,
                PropertyPath,
                TEXT("hard_object"),
                Target->GetPathName(),
                Target->GetClass()->GetPathName());
        }
    }
}

static bool WriteObjectState(
    UObject* Object,
    const FString& SourcePath,
    const FString& Kind,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenObjects)
{
    if (!Object) return true;
    const FString Path = Object->GetPathName();
    if (SeenObjects.Contains(Path)) return true;
    SeenObjects.Add(Path);

    TSharedRef<FJsonObject> ObjectRow = MakeShared<FJsonObject>();
    ObjectRow->SetStringField(TEXT("source_path"), SourcePath);
    ObjectRow->SetStringField(TEXT("object_path"), Path);
    ObjectRow->SetStringField(TEXT("object_kind"), Kind);
    ObjectRow->SetStringField(TEXT("object_class"), Object->GetClass()->GetPathName());
    ObjectRow->SetStringField(TEXT("outer_path"), Object->GetOuter() ? Object->GetOuter()->GetPathName() : FString());
    ObjectRow->SetBoolField(TEXT("archetype_object"), Object->HasAnyFlags(RF_ArchetypeObject));
    ObjectRow->SetStringField(TEXT("provenance"), TEXT("generated_class_owned_object_reflection"));
    if (!Writers.Objects.Write(ObjectRow)) return false;
    ++Counts.Objects;
    if (Kind == TEXT("perception_component_template")) ++Counts.PerceptionComponents;
    else if (Kind == TEXT("stimuli_source_component_template")) ++Counts.StimuliSourceComponents;
    else if (Kind == TEXT("sense_config")) ++Counts.SenseConfigs;

    FWalkContext Context;
    Context.SourcePath = SourcePath;
    Context.OwnerPath = Path;
    Context.OwnerKind = Kind;
    Context.OwnerClass = Object->GetClass()->GetPathName();
    Context.OwnerObject = Object;
    Context.DefaultObject = Object->GetClass()->GetDefaultObject(false);
    Context.Writers = &Writers;
    Context.Counts = &Counts;

    TSet<FString> SeenProperties;
    for (TFieldIterator<FProperty> It(Object->GetClass()); It && !Context.bFailed; ++It)
    {
        FProperty* Property = *It;
        if (!ShouldInspectProperty(Property)) continue;
        const FString Key = (Property->GetOwnerStruct() ? Property->GetOwnerStruct()->GetPathName() : FString()) +
            TEXT("::") + Property->GetName();
        if (SeenProperties.Contains(Key)) continue;
        SeenProperties.Add(Key);
        for (int32 StaticIndex = 0; StaticIndex < Property->ArrayDim && !Context.bFailed; ++StaticIndex)
        {
            const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object, StaticIndex);
            const void* DefaultPtr = Context.DefaultObject
                ? Property->ContainerPtrToValuePtr<void>(Context.DefaultObject, StaticIndex)
                : nullptr;
            const FString Root = Property->GetName();
            const FString PropertyPath = Root +
                (Property->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
            WalkPropertyValue(Property, ValuePtr, DefaultPtr, Root, PropertyPath, 0, Context);
        }
    }
    return !Context.bFailed;
}

static bool WriteAsset(
    const FString& AssetPath,
    UObject* AssetObject,
    FWriters& Writers,
    FCounts& Counts,
    FString& OutError)
{
    UBlueprint* Blueprint = Cast<UBlueprint>(AssetObject);
    UClass* GeneratedClass = Blueprint ? Blueprint->GeneratedClass : Cast<UClass>(AssetObject);

    TSharedRef<FJsonObject> AssetRow = MakeShared<FJsonObject>();
    AssetRow->SetStringField(TEXT("asset_path"), AssetPath);
    AssetRow->SetStringField(TEXT("loaded_object_class"), AssetObject ? AssetObject->GetClass()->GetPathName() : FString());
    AssetRow->SetBoolField(TEXT("loaded"), AssetObject != nullptr);
    AssetRow->SetBoolField(TEXT("is_blueprint"), Blueprint != nullptr);
    AssetRow->SetStringField(TEXT("generated_class"), GeneratedClass ? GeneratedClass->GetPathName() : FString());
    AssetRow->SetStringField(TEXT("provenance"), TEXT("corpus_nominated_asset_plus_loaded_blueprint_generated_class_reflection"));
    if (!Writers.Assets.Write(AssetRow))
    {
        OutError = TEXT("failed writing AI Perception focus asset row: ") + AssetPath;
        return false;
    }

    if (!AssetObject) return true;
    ++Counts.LoadedAssets;
    if (Blueprint) ++Counts.BlueprintAssets;
    if (!GeneratedClass) return true;

    TArray<UObject*> OwnedObjects;
    GetObjectsWithOuter(
        GeneratedClass,
        OwnedObjects,
        EGetObjectsFlags::IncludeNestedObjects,
        RF_Transient,
        EInternalObjectFlags::Garbage);
    OwnedObjects.Sort([](const UObject& A, const UObject& B)
    {
        return A.GetPathName() < B.GetPathName();
    });

    const int32 Limit = FMath::Min(OwnedObjects.Num(), MaxObjectsPerAsset);
    if (OwnedObjects.Num() > Limit) ++Counts.ContainerElementLimitHits;
    TSet<FString> SeenObjects;
    for (int32 Index = 0; Index < Limit; ++Index)
    {
        UObject* Object = OwnedObjects[Index];
        if (!Object || Object->HasAnyFlags(RF_Transient | RF_ClassDefaultObject)) continue;
        if (Object->IsA<UClass>() || Object->IsA<UPackage>()) continue;
        const FString Kind = ObjectKind(Object);
        if (Kind.IsEmpty()) continue;
        if (!WriteObjectState(Object, AssetPath, Kind, Writers, Counts, SeenObjects))
        {
            OutError = TEXT("failed writing AI Perception object state: ") + Object->GetPathName();
            return false;
        }
    }
    return true;
}

static bool WriteManifest(const FString& OutputDir, const FCounts& Counts, bool bSuccess, const FString& Error)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetNumberField(TEXT("schema_version"), SchemaVersion);
    Root->SetStringField(TEXT("schema_name"), TEXT("ai_perception_capture"));
    Root->SetStringField(TEXT("pass"), TEXT("UnrealAssetToolAIPerception"));
    Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetStringField(TEXT("project_name"), FApp::GetProjectName());
    Root->SetBoolField(TEXT("success"), bSuccess);
    Root->SetStringField(TEXT("error"), Error);
    Root->SetBoolField(TEXT("diagnostic_only"), true);
    Root->SetBoolField(TEXT("semantic_promotion"), false);
    Root->SetBoolField(TEXT("runtime_state_captured"), false);
    Root->SetStringField(
        TEXT("provenance"),
        TEXT("corpus_nominated_blueprint_assets_plus_generated_class_owned_object_reflection"));

    TSharedRef<FJsonObject> CountsJson = MakeShared<FJsonObject>();
    CountsJson->SetNumberField(TEXT("focus_assets"), Counts.FocusAssets);
    CountsJson->SetNumberField(TEXT("loaded_assets"), Counts.LoadedAssets);
    CountsJson->SetNumberField(TEXT("blueprint_assets"), Counts.BlueprintAssets);
    CountsJson->SetNumberField(TEXT("perception_components"), Counts.PerceptionComponents);
    CountsJson->SetNumberField(TEXT("stimuli_source_components"), Counts.StimuliSourceComponents);
    CountsJson->SetNumberField(TEXT("sense_configs"), Counts.SenseConfigs);
    CountsJson->SetNumberField(TEXT("objects"), Counts.Objects);
    CountsJson->SetNumberField(TEXT("properties"), Counts.Properties);
    CountsJson->SetNumberField(TEXT("references"), Counts.References);
    CountsJson->SetNumberField(TEXT("truncated_properties"), Counts.TruncatedProperties);
    CountsJson->SetNumberField(TEXT("property_depth_limit_hits"), Counts.PropertyDepthLimitHits);
    CountsJson->SetNumberField(TEXT("property_row_limit_hits"), Counts.PropertyRowLimitHits);
    CountsJson->SetNumberField(TEXT("container_element_limit_hits"), Counts.ContainerElementLimitHits);
    Root->SetObjectField(TEXT("counts"), CountsJson);

    TArray<TSharedPtr<FJsonValue>> Files;
    Files.Add(MakeShared<FJsonValueString>(TEXT("ai_perception_assets.jsonl")));
    Files.Add(MakeShared<FJsonValueString>(TEXT("ai_perception_objects.jsonl")));
    Files.Add(MakeShared<FJsonValueString>(TEXT("ai_perception_properties.jsonl")));
    Files.Add(MakeShared<FJsonValueString>(TEXT("ai_perception_references.jsonl")));
    Root->SetArrayField(TEXT("files"), Files);

    FString Text;
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Text);
    if (!FJsonSerializer::Serialize(Root, Writer)) return false;
    Text.AppendChar(TEXT('\n'));
    return FFileHelper::SaveStringToFile(
        Text,
        *FPaths::Combine(OutputDir, TEXT("ai_perception_capture_manifest.json")),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}
} // namespace UnrealAssetToolAIPerception

UUnrealAssetToolAIPerceptionCommandlet::UUnrealAssetToolAIPerceptionCommandlet()
{
    IsClient = false;
    IsEditor = true;
    IsServer = false;
    LogToConsole = true;
    ShowErrorCount = true;
}

int32 UUnrealAssetToolAIPerceptionCommandlet::Main(const FString& Params)
{
    using namespace UnrealAssetToolAIPerception;

    FString OutputDir;
    if (!FParse::Value(*Params, TEXT("Output="), OutputDir))
    {
        OutputDir = FPaths::Combine(FPaths::ProjectDir(), TEXT(".uatool/ai-perception-capture"));
    }
    OutputDir = FPaths::ConvertRelativePathToFull(OutputDir);
    FPaths::NormalizeDirectoryName(OutputDir);
    IFileManager::Get().MakeDirectory(*OutputDir, true);

    FString FocusFile;
    if (!FParse::Value(*Params, TEXT("FocusFile="), FocusFile) || FocusFile.IsEmpty())
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolAIPerception requires -FocusFile=<path>"));
        return 2;
    }
    FocusFile = FPaths::ConvertRelativePathToFull(FocusFile);

    TArray<FString> FocusAssets;
    if (!FFileHelper::LoadFileToStringArray(FocusAssets, *FocusFile))
    {
        UE_LOG(LogTemp, Error, TEXT("Could not read AI Perception focus file: %s"), *FocusFile);
        return 3;
    }
    FocusAssets.RemoveAll([](const FString& Value) { return Value.TrimStartAndEnd().IsEmpty(); });
    for (FString& Value : FocusAssets) Value = Value.TrimStartAndEnd();
    FocusAssets.Sort();
    TArray<FString> UniqueAssets;
    for (const FString& Value : FocusAssets)
    {
        if (UniqueAssets.IsEmpty() || UniqueAssets.Last() != Value) UniqueAssets.Add(Value);
    }
    FocusAssets = MoveTemp(UniqueAssets);

    FWriters Writers;
    FCounts Counts;
    Counts.FocusAssets = FocusAssets.Num();
    FString Error;
    bool bSuccess = Writers.Open(OutputDir);
    if (!bSuccess) Error = TEXT("could not open one or more AI Perception capture JSONL writers");

    if (bSuccess)
    {
        for (const FString& AssetPath : FocusAssets)
        {
            UObject* AssetObject = StaticLoadObject(UObject::StaticClass(), nullptr, *AssetPath);
            if (!WriteAsset(AssetPath, AssetObject, Writers, Counts, Error))
            {
                bSuccess = false;
                break;
            }
        }
    }

    if (!Writers.Close())
    {
        bSuccess = false;
        if (Error.IsEmpty()) Error = TEXT("failed to finalize one or more AI Perception capture JSONL writers");
    }
    if (!WriteManifest(OutputDir, Counts, bSuccess, Error))
    {
        UE_LOG(LogTemp, Error, TEXT("Failed to write AI Perception capture manifest"));
        return 4;
    }

    UE_LOG(
        LogTemp,
        Display,
        TEXT("UnrealAssetToolAIPerception: success=%s focus=%lld loaded=%lld blueprints=%lld perception_components=%lld stimuli_sources=%lld sense_configs=%lld objects=%lld properties=%lld references=%lld"),
        bSuccess ? TEXT("true") : TEXT("false"),
        Counts.FocusAssets,
        Counts.LoadedAssets,
        Counts.BlueprintAssets,
        Counts.PerceptionComponents,
        Counts.StimuliSourceComponents,
        Counts.SenseConfigs,
        Counts.Objects,
        Counts.Properties,
        Counts.References);
    return bSuccess ? 0 : 5;
}

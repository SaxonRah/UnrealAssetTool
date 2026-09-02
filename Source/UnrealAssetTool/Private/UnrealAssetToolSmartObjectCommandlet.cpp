#include "UnrealAssetToolSmartObjectCommandlet.h"

#include "AssetRegistry/AssetData.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "HAL/FileManager.h"
#include "Json.h"
#include "Misc/App.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/Package.h"
#include "UObject/SoftObjectPtr.h"
#include "UObject/UObjectHash.h"
#include "UObject/UnrealType.h"

namespace UnrealAssetToolSmartObject
{
constexpr int32 SchemaVersion = 1;
constexpr int32 MaxExportChars = 65536;
constexpr int32 MaxPropertyDepth = 16;
constexpr int32 MaxElementsPerContainer = 4096;
constexpr int32 MaxPropertyRowsPerObject = 65536;
constexpr int32 MaxNestedObjectsPerDefinition = 4096;

struct FCounts
{
    int64 AssetsConsidered = 0;
    int64 CandidateAssets = 0;
    int64 LoadedAssets = 0;
    int64 DefinitionAssets = 0;
    int64 Objects = 0;
    int64 NestedObjects = 0;
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
        if (!Archive.IsValid())
        {
            return false;
        }
        FString Line;
        const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
            TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Line);
        if (!FJsonSerializer::Serialize(Object, Writer))
        {
            return false;
        }
        Line.AppendChar(TEXT('\n'));
        FTCHARToUTF8 Utf8(*Line);
        Archive->Serialize((void*)Utf8.Get(), Utf8.Length());
        return !Archive->IsError();
    }

    bool Close()
    {
        if (!Archive.IsValid())
        {
            return true;
        }
        const bool bClosed = Archive->Close();
        const bool bOk = bClosed && !Archive->IsError();
        Archive.Reset();
        return bOk;
    }

    ~FJsonlWriter()
    {
        Close();
    }

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
        return Assets.Open(FPaths::Combine(OutputDir, TEXT("smartobject_assets.jsonl"))) &&
            Objects.Open(FPaths::Combine(OutputDir, TEXT("smartobject_objects.jsonl"))) &&
            Properties.Open(FPaths::Combine(OutputDir, TEXT("smartobject_properties.jsonl"))) &&
            References.Open(FPaths::Combine(OutputDir, TEXT("smartobject_references.jsonl")));
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
    if (!Property)
    {
        return false;
    }
    constexpr EPropertyFlags Rejected =
        CPF_Transient | CPF_DuplicateTransient | CPF_NonPIEDuplicateTransient |
        CPF_Deprecated | CPF_SkipSerialization;
    return !Property->HasAnyPropertyFlags(Rejected);
}

static bool ClassInheritsName(const UClass* Class, const TCHAR* BaseName)
{
    for (const UClass* It = Class; It; It = It->GetSuperClass())
    {
        if (It->GetName().Equals(BaseName, ESearchCase::CaseSensitive))
        {
            return true;
        }
    }
    return false;
}

static bool IsDefinitionClass(const UClass* Class)
{
    return ClassInheritsName(Class, TEXT("SmartObjectDefinition"));
}

static FString AssetTag(const FAssetData& Asset, const TCHAR* Name)
{
    FString Value;
    Asset.GetTagValue(FName(Name), Value);
    return Value;
}

static FString CandidateText(const FAssetData& Asset)
{
    TArray<FString> Parts;
    Parts.Reserve(5);
    Parts.Add(Asset.AssetClassPath.ToString());
    Parts.Add(AssetTag(Asset, TEXT("NativeClass")));
    Parts.Add(AssetTag(Asset, TEXT("ParentClass")));
    Parts.Add(AssetTag(Asset, TEXT("NativeParentClass")));
    Parts.Add(AssetTag(Asset, TEXT("GeneratedClass")));
    return FString::Join(Parts, TEXT("\n"));
}

static bool IsDefinitionCandidate(const FAssetData& Asset)
{
    const FString Lower = CandidateText(Asset).ToLower();
    return Lower.Contains(TEXT("smartobjectdefinition")) ||
        Lower.Contains(TEXT("/script/smartobjectsmodule.smartobjectdefinition"));
}

static FString ExportProperty(
    const FProperty* Property,
    const void* ValuePtr,
    UObject* Owner,
    bool& bTruncated)
{
    bTruncated = false;
    if (!Property || !ValuePtr)
    {
        return FString();
    }
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
    if (!Context.Writers || !Context.Counts || TargetPath.IsEmpty() || Context.bFailed)
    {
        return;
    }
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
    const FString& RootProperty,
    const FString& PropertyPath,
    int32 Depth,
    int32 ElementCount,
    FWalkContext& Context)
{
    if (!Context.Writers || !Context.Counts || !Property || Context.bFailed)
    {
        return;
    }
    if (Context.Rows >= MaxPropertyRowsPerObject)
    {
        ++Context.Counts->PropertyRowLimitHits;
        return;
    }

    bool bTruncated = false;
    const FString Value = ExportProperty(Property, ValuePtr, Context.OwnerObject, bTruncated);
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
    if (ElementCount >= 0)
    {
        Row->SetNumberField(TEXT("element_count"), ElementCount);
    }
    Row->SetStringField(TEXT("value"), Value);
    Row->SetBoolField(TEXT("truncated"), bTruncated);
    if (!Context.Writers->Properties.Write(Row))
    {
        Context.bFailed = true;
        return;
    }
    ++Context.Rows;
    ++Context.Counts->Properties;
    if (bTruncated)
    {
        ++Context.Counts->TruncatedProperties;
    }
}

static void WalkPropertyValue(
    const FProperty* Property,
    const void* ValuePtr,
    const FString& RootProperty,
    const FString& PropertyPath,
    int32 Depth,
    FWalkContext& Context)
{
    if (!Property || !ValuePtr || Context.bFailed)
    {
        return;
    }
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
        EmitProperty(Property, ValuePtr, RootProperty, PropertyPath, Depth, Helper.Num(), Context);
        const int32 Limit = FMath::Min(Helper.Num(), MaxElementsPerContainer);
        if (Helper.Num() > Limit)
        {
            ++Context.Counts->ContainerElementLimitHits;
        }
        for (int32 Index = 0; Index < Limit && !Context.bFailed && Context.Rows < MaxPropertyRowsPerObject; ++Index)
        {
            WalkPropertyValue(
                ArrayProperty->Inner,
                Helper.GetRawPtr(Index),
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
        EmitProperty(Property, ValuePtr, RootProperty, PropertyPath, Depth, Helper.Num(), Context);
        int32 Emitted = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && Emitted < MaxElementsPerContainer &&
            !Context.bFailed && Context.Rows < MaxPropertyRowsPerObject; ++Index)
        {
            if (!Helper.IsValidIndex(Index)) continue;
            WalkPropertyValue(
                SetProperty->ElementProp,
                Helper.GetElementPtr(Index),
                RootProperty,
                FString::Printf(TEXT("%s{%d}"), *PropertyPath, Emitted++),
                Depth + 1,
                Context);
        }
        if (Helper.Num() > Emitted)
        {
            ++Context.Counts->ContainerElementLimitHits;
        }
        return;
    }

    if (const FMapProperty* MapProperty = CastField<FMapProperty>(Property))
    {
        FScriptMapHelper Helper(MapProperty, ValuePtr);
        EmitProperty(Property, ValuePtr, RootProperty, PropertyPath, Depth, Helper.Num(), Context);
        int32 Emitted = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && Emitted < MaxElementsPerContainer &&
            !Context.bFailed && Context.Rows < MaxPropertyRowsPerObject; ++Index)
        {
            if (!Helper.IsValidIndex(Index)) continue;
            const FString Base = FString::Printf(TEXT("%s{%d}"), *PropertyPath, Emitted++);
            WalkPropertyValue(MapProperty->KeyProp, Helper.GetKeyPtr(Index), RootProperty, Base + TEXT(".key"), Depth + 1, Context);
            WalkPropertyValue(MapProperty->ValueProp, Helper.GetValuePtr(Index), RootProperty, Base + TEXT(".value"), Depth + 1, Context);
        }
        if (Helper.Num() > Emitted)
        {
            ++Context.Counts->ContainerElementLimitHits;
        }
        return;
    }

    if (const FStructProperty* StructProperty = CastField<FStructProperty>(Property))
    {
        EmitProperty(Property, ValuePtr, RootProperty, PropertyPath, Depth, -1, Context);
        if (!StructProperty->Struct)
        {
            return;
        }
        for (TFieldIterator<FProperty> It(StructProperty->Struct); It && !Context.bFailed; ++It)
        {
            const FProperty* Inner = *It;
            if (!ShouldInspectProperty(Inner)) continue;
            for (int32 StaticIndex = 0; StaticIndex < Inner->ArrayDim && !Context.bFailed; ++StaticIndex)
            {
                const void* InnerValue = Inner->ContainerPtrToValuePtr<void>(ValuePtr, StaticIndex);
                const FString ChildPath = PropertyPath + TEXT(".") + Inner->GetName() +
                    (Inner->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
                WalkPropertyValue(Inner, InnerValue, RootProperty, ChildPath, Depth + 1, Context);
            }
        }
        return;
    }

    EmitProperty(Property, ValuePtr, RootProperty, PropertyPath, Depth, -1, Context);

    if (const FSoftObjectProperty* SoftProperty = CastField<FSoftObjectProperty>(Property))
    {
        const FSoftObjectPtr* SoftPtr = static_cast<const FSoftObjectPtr*>(ValuePtr);
        if (SoftPtr && !SoftPtr->IsNull())
        {
            EmitReference(
                Context,
                RootProperty,
                PropertyPath,
                TEXT("soft_object"),
                SoftPtr->ToSoftObjectPath().ToString(),
                FString());
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
    const FString& ObjectKind,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenObjects)
{
    if (!Object)
    {
        return true;
    }
    const FString ObjectPath = Object->GetPathName();
    if (SeenObjects.Contains(ObjectPath))
    {
        return true;
    }
    SeenObjects.Add(ObjectPath);

    TSharedRef<FJsonObject> ObjectRow = MakeShared<FJsonObject>();
    ObjectRow->SetStringField(TEXT("source_path"), SourcePath);
    ObjectRow->SetStringField(TEXT("object_path"), ObjectPath);
    ObjectRow->SetStringField(TEXT("object_kind"), ObjectKind);
    ObjectRow->SetStringField(TEXT("object_class"), Object->GetClass()->GetPathName());
    ObjectRow->SetStringField(TEXT("outer_path"), Object->GetOuter() ? Object->GetOuter()->GetPathName() : FString());
    ObjectRow->SetBoolField(TEXT("native_class"), Object->GetClass()->HasAnyClassFlags(CLASS_Native));
    ObjectRow->SetStringField(TEXT("provenance"), TEXT("loaded_object_reflection"));
    if (!Writers.Objects.Write(ObjectRow))
    {
        return false;
    }
    ++Counts.Objects;

    FWalkContext Context;
    Context.SourcePath = SourcePath;
    Context.OwnerPath = ObjectPath;
    Context.OwnerKind = ObjectKind;
    Context.OwnerClass = Object->GetClass()->GetPathName();
    Context.OwnerObject = Object;
    Context.Writers = &Writers;
    Context.Counts = &Counts;

    TSet<FString> SeenRootProperties;
    for (UClass* Class = Object->GetClass(); Class && Class != UObject::StaticClass(); Class = Class->GetSuperClass())
    {
        for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It && !Context.bFailed; ++It)
        {
            FProperty* Property = *It;
            if (!ShouldInspectProperty(Property)) continue;
            const FString PropertyKey = Class->GetPathName() + TEXT("::") + Property->GetName();
            if (SeenRootProperties.Contains(PropertyKey)) continue;
            SeenRootProperties.Add(PropertyKey);
            for (int32 StaticIndex = 0; StaticIndex < Property->ArrayDim && !Context.bFailed; ++StaticIndex)
            {
                const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object, StaticIndex);
                const FString Root = Property->GetName();
                const FString Path = Root +
                    (Property->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
                WalkPropertyValue(Property, ValuePtr, Root, Path, 0, Context);
            }
        }
    }
    return !Context.bFailed;
}

static bool ShouldCaptureNested(UObject* Object)
{
    if (!Object || Object->HasAnyFlags(RF_Transient | RF_ClassDefaultObject | RF_ArchetypeObject))
    {
        return false;
    }
    if (Object->IsA<UClass>() || Object->IsA<UPackage>())
    {
        return false;
    }
    return true;
}

static bool WriteNestedObjects(
    UObject* Definition,
    const FString& SourcePath,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenObjects)
{
    if (!Definition)
    {
        return true;
    }
    TArray<UObject*> Nested;
    GetObjectsWithOuter(
        Definition,
        Nested,
        EGetObjectsFlags::IncludeNestedObjects,
        RF_Transient,
        EInternalObjectFlags::Garbage);
    Nested.Sort([](const UObject& A, const UObject& B)
    {
        return A.GetPathName() < B.GetPathName();
    });
    const int32 Limit = FMath::Min(Nested.Num(), MaxNestedObjectsPerDefinition);
    if (Nested.Num() > Limit)
    {
        ++Counts.ContainerElementLimitHits;
    }
    for (int32 Index = 0; Index < Limit; ++Index)
    {
        UObject* Object = Nested[Index];
        if (!ShouldCaptureNested(Object)) continue;
        const bool bWasSeen = SeenObjects.Contains(Object->GetPathName());
        if (!WriteObjectState(Object, SourcePath, TEXT("nested_object"), Writers, Counts, SeenObjects))
        {
            return false;
        }
        if (!bWasSeen)
        {
            ++Counts.NestedObjects;
        }
    }
    return true;
}

static bool WriteAsset(
    const FAssetData& Asset,
    UObject* Object,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenObjects,
    FString& OutError)
{
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    const bool bDefinition = Object && IsDefinitionClass(Object->GetClass());

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), AssetPath);
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("asset_name"), Asset.AssetName.ToString());
    Row->SetStringField(TEXT("asset_class"), Asset.AssetClassPath.ToString());
    Row->SetStringField(TEXT("native_class_tag"), AssetTag(Asset, TEXT("NativeClass")));
    Row->SetStringField(TEXT("parent_class_tag"), AssetTag(Asset, TEXT("ParentClass")));
    Row->SetStringField(TEXT("native_parent_class_tag"), AssetTag(Asset, TEXT("NativeParentClass")));
    Row->SetStringField(TEXT("generated_class_tag"), AssetTag(Asset, TEXT("GeneratedClass")));
    Row->SetStringField(TEXT("loaded_object_class"), Object ? Object->GetClass()->GetPathName() : FString());
    Row->SetBoolField(TEXT("loaded"), Object != nullptr);
    Row->SetBoolField(TEXT("is_definition"), bDefinition);
    Row->SetStringField(TEXT("provenance"), TEXT("asset_registry_class_candidate_plus_loaded_object_reflection"));
    if (!Writers.Assets.Write(Row))
    {
        OutError = TEXT("failed writing Smart Object asset row: ") + AssetPath;
        return false;
    }

    if (!Object || !bDefinition)
    {
        return true;
    }
    ++Counts.DefinitionAssets;
    if (!WriteObjectState(Object, AssetPath, TEXT("definition_asset"), Writers, Counts, SeenObjects))
    {
        OutError = TEXT("failed writing SmartObjectDefinition state: ") + AssetPath;
        return false;
    }
    if (!WriteNestedObjects(Object, AssetPath, Writers, Counts, SeenObjects))
    {
        OutError = TEXT("failed writing nested Smart Object definition state: ") + AssetPath;
        return false;
    }
    return true;
}

static bool WriteManifest(
    const FString& OutputDir,
    const FCounts& Counts,
    bool bSuccess,
    const FString& Error)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetNumberField(TEXT("schema_version"), SchemaVersion);
    Root->SetStringField(TEXT("schema_name"), TEXT("smartobject_capture"));
    Root->SetStringField(TEXT("pass"), TEXT("UnrealAssetToolSmartObject"));
    Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetStringField(TEXT("project_name"), FApp::GetProjectName());
    Root->SetBoolField(TEXT("success"), bSuccess);
    Root->SetStringField(TEXT("error"), Error);
    Root->SetBoolField(TEXT("diagnostic_only"), true);
    Root->SetBoolField(TEXT("semantic_promotion"), false);
    Root->SetBoolField(TEXT("runtime_state_captured"), false);
    Root->SetStringField(
        TEXT("provenance"),
        TEXT("asset_registry_class_candidate_plus_loaded_definition_recursive_reflection"));

    TSharedRef<FJsonObject> CountsJson = MakeShared<FJsonObject>();
    CountsJson->SetNumberField(TEXT("assets_considered"), Counts.AssetsConsidered);
    CountsJson->SetNumberField(TEXT("candidate_assets"), Counts.CandidateAssets);
    CountsJson->SetNumberField(TEXT("loaded_assets"), Counts.LoadedAssets);
    CountsJson->SetNumberField(TEXT("definition_assets"), Counts.DefinitionAssets);
    CountsJson->SetNumberField(TEXT("smartobject_objects"), Counts.Objects);
    CountsJson->SetNumberField(TEXT("nested_objects"), Counts.NestedObjects);
    CountsJson->SetNumberField(TEXT("smartobject_properties"), Counts.Properties);
    CountsJson->SetNumberField(TEXT("smartobject_references"), Counts.References);
    CountsJson->SetNumberField(TEXT("truncated_properties"), Counts.TruncatedProperties);
    CountsJson->SetNumberField(TEXT("property_depth_limit_hits"), Counts.PropertyDepthLimitHits);
    CountsJson->SetNumberField(TEXT("property_row_limit_hits"), Counts.PropertyRowLimitHits);
    CountsJson->SetNumberField(TEXT("container_element_limit_hits"), Counts.ContainerElementLimitHits);
    Root->SetObjectField(TEXT("counts"), CountsJson);

    TArray<TSharedPtr<FJsonValue>> Files;
    Files.Add(MakeShared<FJsonValueString>(TEXT("smartobject_assets.jsonl")));
    Files.Add(MakeShared<FJsonValueString>(TEXT("smartobject_objects.jsonl")));
    Files.Add(MakeShared<FJsonValueString>(TEXT("smartobject_properties.jsonl")));
    Files.Add(MakeShared<FJsonValueString>(TEXT("smartobject_references.jsonl")));
    Root->SetArrayField(TEXT("files"), Files);

    FString Text;
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Text);
    if (!FJsonSerializer::Serialize(Root, Writer)) return false;
    Text.AppendChar(TEXT('\n'));
    return FFileHelper::SaveStringToFile(
        Text,
        *FPaths::Combine(OutputDir, TEXT("smartobject_capture_manifest.json")),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}
} // namespace UnrealAssetToolSmartObject

UUnrealAssetToolSmartObjectCommandlet::UUnrealAssetToolSmartObjectCommandlet()
{
    IsClient = false;
    IsEditor = true;
    IsServer = false;
    LogToConsole = true;
    ShowErrorCount = true;
}

int32 UUnrealAssetToolSmartObjectCommandlet::Main(const FString& Params)
{
    using namespace UnrealAssetToolSmartObject;

    FString OutputDir;
    if (!FParse::Value(*Params, TEXT("Output="), OutputDir))
    {
        OutputDir = FPaths::Combine(FPaths::ProjectDir(), TEXT(".uatool/smartobject-capture"));
    }
    OutputDir = FPaths::ConvertRelativePathToFull(OutputDir);
    FPaths::NormalizeDirectoryName(OutputDir);
    IFileManager::Get().MakeDirectory(*OutputDir, true);

    FWriters Writers;
    FCounts Counts;
    FString Error;
    bool bSuccess = Writers.Open(OutputDir);
    if (!bSuccess)
    {
        Error = TEXT("could not open one or more Smart Object capture JSONL writers");
    }

    if (bSuccess)
    {
        FAssetRegistryModule& AssetRegistryModule =
            FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
        IAssetRegistry& Registry = AssetRegistryModule.Get();
        Registry.SearchAllAssets(true);

        TArray<FAssetData> Assets;
        Registry.GetAllAssets(Assets, true);
        Assets.Sort([](const FAssetData& A, const FAssetData& B)
        {
            return A.GetSoftObjectPath().ToString() < B.GetSoftObjectPath().ToString();
        });

        TSet<FString> SeenObjects;
        for (const FAssetData& Asset : Assets)
        {
            ++Counts.AssetsConsidered;
            const FString Package = Asset.PackageName.ToString();
            if (Package.StartsWith(TEXT("/Engine/"), ESearchCase::IgnoreCase))
            {
                continue;
            }
            if (!IsDefinitionCandidate(Asset))
            {
                continue;
            }
            ++Counts.CandidateAssets;
            UObject* Object = Asset.GetAsset();
            if (Object)
            {
                ++Counts.LoadedAssets;
            }
            if (!WriteAsset(Asset, Object, Writers, Counts, SeenObjects, Error))
            {
                bSuccess = false;
                break;
            }
        }
    }

    if (!Writers.Close())
    {
        bSuccess = false;
        if (Error.IsEmpty())
        {
            Error = TEXT("failed closing one or more Smart Object capture writers");
        }
    }

    if (!WriteManifest(OutputDir, Counts, bSuccess, Error))
    {
        UE_LOG(LogTemp, Error, TEXT("Could not write Smart Object capture manifest: %s"), *OutputDir);
        return 3;
    }
    if (!bSuccess)
    {
        UE_LOG(LogTemp, Error, TEXT("Focused Smart Object capture failed: %s"), *Error);
        return 4;
    }

    UE_LOG(
        LogTemp,
        Display,
        TEXT("UnrealAssetTool Smart Object capture: candidates=%lld loaded=%lld definitions=%lld objects=%lld properties=%lld references=%lld nested=%lld"),
        Counts.CandidateAssets,
        Counts.LoadedAssets,
        Counts.DefinitionAssets,
        Counts.Objects,
        Counts.Properties,
        Counts.References,
        Counts.NestedObjects);
    UE_LOG(LogTemp, Display, TEXT("UnrealAssetTool Smart Object capture output: %s"), *OutputDir);
    return 0;
}

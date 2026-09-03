#include "UnrealAssetToolSkeletalMeshPhysicsAssetCommandlet.h"

#include "AssetRegistry/AssetData.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "HAL/FileManager.h"
#include "Json.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/SoftObjectPtr.h"
#include "UObject/UObjectGlobals.h"
#include "UObject/UObjectHash.h"
#include "UObject/UnrealType.h"

namespace UnrealAssetToolSkeletalMeshPhysicsAsset
{
constexpr int32 SchemaVersion = 1;
constexpr int32 MaxExportChars = 65536;
constexpr int32 MaxDepth = 16;
constexpr int32 MaxContainerElements = 4096;
constexpr int32 MaxPropertyRowsPerOwner = 65536;

static const TCHAR* SkeletalMeshClassPath = TEXT("/Script/Engine.SkeletalMesh");
static const TCHAR* PhysicsAssetClassPath = TEXT("/Script/Engine.PhysicsAsset");

static const TCHAR* RegistryTagNames[] = {
    TEXT("Skeleton"),
    TEXT("PhysicsAsset"),
    TEXT("ShadowPhysicsAsset"),
    TEXT("LODSettings"),
    TEXT("LODs"),
    TEXT("Bones"),
    TEXT("MorphTargets"),
    TEXT("MorphTargetNames"),
    TEXT("SkinWeightProfiles"),
    TEXT("NaniteEnabled"),
    TEXT("NaniteTriangles"),
    TEXT("NaniteVertices"),
    TEXT("Triangles"),
    TEXT("Vertices"),
    TEXT("Bodies"),
    TEXT("Constraints"),
    TEXT("PreviewSkeletalMesh"),
};

struct FCounts
{
    int64 RegistryCandidates = 0;
    int64 LoadedAssets = 0;
    int64 LoadFailures = 0;
    int64 SkeletalMeshes = 0;
    int64 PhysicsAssets = 0;
    int64 AssetProperties = 0;
    int64 AssetReferences = 0;
    int64 OwnedObjects = 0;
    int64 OwnedObjectProperties = 0;
    int64 OwnedObjectReferences = 0;
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
    FJsonlWriter AssetProperties;
    FJsonlWriter AssetReferences;
    FJsonlWriter OwnedObjects;
    FJsonlWriter OwnedObjectProperties;
    FJsonlWriter OwnedObjectReferences;

    bool Open(const FString& OutputDir)
    {
        return Assets.Open(FPaths::Combine(OutputDir, TEXT("skeletalmesh_physicsasset_assets.jsonl"))) &&
            AssetProperties.Open(FPaths::Combine(OutputDir, TEXT("skeletalmesh_physicsasset_asset_properties.jsonl"))) &&
            AssetReferences.Open(FPaths::Combine(OutputDir, TEXT("skeletalmesh_physicsasset_asset_references.jsonl"))) &&
            OwnedObjects.Open(FPaths::Combine(OutputDir, TEXT("skeletalmesh_physicsasset_owned_objects.jsonl"))) &&
            OwnedObjectProperties.Open(FPaths::Combine(OutputDir, TEXT("skeletalmesh_physicsasset_owned_object_properties.jsonl"))) &&
            OwnedObjectReferences.Open(FPaths::Combine(OutputDir, TEXT("skeletalmesh_physicsasset_owned_object_references.jsonl")));
    }

    bool Close()
    {
        bool bOk = true;
        bOk = Assets.Close() && bOk;
        bOk = AssetProperties.Close() && bOk;
        bOk = AssetReferences.Close() && bOk;
        bOk = OwnedObjects.Close() && bOk;
        bOk = OwnedObjectProperties.Close() && bOk;
        bOk = OwnedObjectReferences.Close() && bOk;
        return bOk;
    }
};

struct FOwnerState
{
    int32 Rows = 0;
};

static FString NormalizeAbsolutePath(const FString& InPath)
{
    FString Path = FPaths::ConvertRelativePathToFull(InPath);
    FPaths::NormalizeFilename(Path);
    FPaths::CollapseRelativeDirectories(Path);
    return Path;
}

static bool IsInsideDirectory(const FString& File, const FString& Directory)
{
    FString NormalizedFile = NormalizeAbsolutePath(File);
    FString NormalizedDirectory = NormalizeAbsolutePath(Directory);
    if (!NormalizedDirectory.EndsWith(TEXT("/")))
    {
        NormalizedDirectory.AppendChar(TEXT('/'));
    }
    return NormalizedFile.StartsWith(NormalizedDirectory, ESearchCase::IgnoreCase);
}

static bool AssetInScope(const FAssetData& Asset, const FString& ProjectDir, bool bIncludeEngine)
{
    if (bIncludeEngine) return true;
    FString Filename;
    FPackageName::DoesPackageExist(Asset.PackageName.ToString(), &Filename, false);
    if (Filename.IsEmpty()) return false;
    return IsInsideDirectory(Filename, ProjectDir);
}

static bool IsFocusClass(const FString& ClassPath)
{
    return ClassPath.Equals(SkeletalMeshClassPath, ESearchCase::CaseSensitive) ||
        ClassPath.Equals(PhysicsAssetClassPath, ESearchCase::CaseSensitive);
}

static FString AssetKind(const FString& ClassPath)
{
    if (ClassPath.Equals(SkeletalMeshClassPath, ESearchCase::CaseSensitive)) return TEXT("skeletal_mesh");
    if (ClassPath.Equals(PhysicsAssetClassPath, ESearchCase::CaseSensitive)) return TEXT("physics_asset");
    return TEXT("unknown");
}

static bool ShouldInspectProperty(const FProperty* Property)
{
    if (!Property) return false;
    constexpr EPropertyFlags Rejected =
        CPF_Transient | CPF_DuplicateTransient | CPF_NonPIEDuplicateTransient |
        CPF_Deprecated | CPF_SkipSerialization;
    return !Property->HasAnyPropertyFlags(Rejected);
}

static FString ExportProperty(const FProperty* Property, const void* ValuePtr, UObject* ExportOwner, bool& bTruncated)
{
    bTruncated = false;
    if (!Property || !ValuePtr) return FString();
    FString Text;
    Property->ExportTextItem_Direct(Text, ValuePtr, nullptr, ExportOwner, PPF_None, nullptr);
    if (Text.Len() > MaxExportChars)
    {
        Text.LeftInline(MaxExportChars, EAllowShrinking::No);
        bTruncated = true;
    }
    return Text;
}

static int32 ContainerElementCount(const FProperty* Property, const void* ValuePtr)
{
    if (!Property || !ValuePtr) return -1;
    if (const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
    {
        FScriptArrayHelper Helper(ArrayProperty, const_cast<void*>(ValuePtr));
        return Helper.Num();
    }
    if (const FSetProperty* SetProperty = CastField<FSetProperty>(Property))
    {
        FScriptSetHelper Helper(SetProperty, const_cast<void*>(ValuePtr));
        return Helper.Num();
    }
    if (const FMapProperty* MapProperty = CastField<FMapProperty>(Property))
    {
        FScriptMapHelper Helper(MapProperty, const_cast<void*>(ValuePtr));
        return Helper.Num();
    }
    return -1;
}

static bool WriteReference(
    const FProperty* Property,
    const void* ValuePtr,
    const FString& AssetPath,
    const FString& OwnerPath,
    const FString& OwnerKind,
    const FString& OwnerType,
    const FString& RootProperty,
    const FString& PropertyPath,
    FJsonlWriter& Writer,
    int64& Count)
{
    FString TargetPath;
    FString TargetClass;
    FString Kind;

    if (const FSoftObjectProperty* SoftProperty = CastField<FSoftObjectProperty>(Property))
    {
        const FSoftObjectPtr* Ptr = static_cast<const FSoftObjectPtr*>(ValuePtr);
        if (Ptr && !Ptr->IsNull())
        {
            TargetPath = Ptr->ToSoftObjectPath().ToString();
            Kind = TEXT("soft_object");
        }
    }
    else if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
    {
        if (UObject* Target = ObjectProperty->GetObjectPropertyValue(ValuePtr))
        {
            TargetPath = Target->GetPathName();
            TargetClass = Target->GetClass()->GetPathName();
            Kind = TEXT("hard_object");
        }
    }

    if (TargetPath.IsEmpty()) return true;

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), AssetPath);
    Row->SetStringField(TEXT("owner_path"), OwnerPath);
    Row->SetStringField(TEXT("owner_kind"), OwnerKind);
    Row->SetStringField(TEXT("owner_type"), OwnerType);
    Row->SetStringField(TEXT("root_property"), RootProperty);
    Row->SetStringField(TEXT("property_path"), PropertyPath);
    Row->SetStringField(TEXT("reference_kind"), Kind);
    Row->SetStringField(TEXT("target_path"), TargetPath);
    Row->SetStringField(TEXT("target_class"), TargetClass);
    if (!Writer.Write(Row)) return false;
    ++Count;
    return true;
}

static bool WritePropertyRecursive(
    const FProperty* Property,
    const void* ValuePtr,
    const void* DefaultPtr,
    UObject* ExportOwner,
    UObject* DefaultExportOwner,
    const FString& AssetPath,
    const FString& OwnerPath,
    const FString& OwnerKind,
    const FString& OwnerType,
    const FString& RootProperty,
    const FString& PropertyPath,
    int32 Depth,
    FJsonlWriter& PropertyWriter,
    FJsonlWriter& ReferenceWriter,
    FOwnerState& State,
    FCounts& Counts,
    int64& PropertyCount,
    int64& ReferenceCount)
{
    if (!Property || !ValuePtr || !ShouldInspectProperty(Property)) return true;
    if (State.Rows >= MaxPropertyRowsPerOwner)
    {
        ++Counts.PropertyRowLimitHits;
        return true;
    }

    bool bTruncated = false;
    const FString Value = ExportProperty(Property, ValuePtr, ExportOwner, bTruncated);
    bool bDefaultTruncated = false;
    const FString DefaultValue = DefaultPtr
        ? ExportProperty(Property, DefaultPtr, DefaultExportOwner, bDefaultTruncated)
        : FString();

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), AssetPath);
    Row->SetStringField(TEXT("owner_path"), OwnerPath);
    Row->SetStringField(TEXT("owner_kind"), OwnerKind);
    Row->SetStringField(TEXT("owner_type"), OwnerType);
    Row->SetNumberField(TEXT("property_index"), State.Rows);
    Row->SetNumberField(TEXT("depth"), Depth);
    Row->SetStringField(TEXT("declaring_type"), Property->GetOwnerStruct() ? Property->GetOwnerStruct()->GetPathName() : FString());
    Row->SetStringField(TEXT("root_property"), RootProperty);
    Row->SetStringField(TEXT("property_name"), Property->GetName());
    Row->SetStringField(TEXT("property_path"), PropertyPath);
    Row->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
    Row->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
    Row->SetStringField(TEXT("value"), Value);
    Row->SetBoolField(TEXT("default_present"), DefaultPtr != nullptr);
    if (DefaultPtr)
    {
        Row->SetStringField(TEXT("default_value"), DefaultValue);
        Row->SetBoolField(TEXT("differs_from_default"), !Property->Identical(ValuePtr, DefaultPtr, PPF_None));
    }
    Row->SetBoolField(TEXT("truncated"), bTruncated || bDefaultTruncated);
    const int32 ElementCount = ContainerElementCount(Property, ValuePtr);
    if (ElementCount >= 0) Row->SetNumberField(TEXT("element_count"), ElementCount);
    if (!PropertyWriter.Write(Row)) return false;
    ++State.Rows;
    ++PropertyCount;
    if (bTruncated || bDefaultTruncated) ++Counts.TruncatedProperties;

    if (!WriteReference(
            Property, ValuePtr, AssetPath, OwnerPath, OwnerKind, OwnerType,
            RootProperty, PropertyPath, ReferenceWriter, ReferenceCount))
    {
        return false;
    }

    if (Depth >= MaxDepth)
    {
        if (CastField<FStructProperty>(Property) || CastField<FArrayProperty>(Property) ||
            CastField<FSetProperty>(Property) || CastField<FMapProperty>(Property))
        {
            ++Counts.PropertyDepthLimitHits;
        }
        return true;
    }

    if (const FStructProperty* StructProperty = CastField<FStructProperty>(Property))
    {
        if (!StructProperty->Struct) return true;
        for (TFieldIterator<FProperty> It(StructProperty->Struct); It; ++It)
        {
            const FProperty* Child = *It;
            if (!ShouldInspectProperty(Child)) continue;
            for (int32 StaticIndex = 0; StaticIndex < Child->ArrayDim; ++StaticIndex)
            {
                const void* ChildPtr = Child->ContainerPtrToValuePtr<void>(ValuePtr, StaticIndex);
                const void* ChildDefaultPtr = DefaultPtr
                    ? Child->ContainerPtrToValuePtr<void>(DefaultPtr, StaticIndex)
                    : nullptr;
                FString ChildPath = PropertyPath + TEXT(".") + Child->GetName();
                if (Child->ArrayDim > 1)
                    ChildPath += FString::Printf(TEXT("[%d]"), StaticIndex);
                if (!WritePropertyRecursive(
                        Child, ChildPtr, ChildDefaultPtr, ExportOwner, DefaultExportOwner,
                        AssetPath, OwnerPath, OwnerKind, OwnerType, RootProperty, ChildPath,
                        Depth + 1, PropertyWriter, ReferenceWriter, State, Counts,
                        PropertyCount, ReferenceCount))
                {
                    return false;
                }
            }
        }
    }
    else if (const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
    {
        FScriptArrayHelper Helper(ArrayProperty, const_cast<void*>(ValuePtr));
        TUniquePtr<FScriptArrayHelper> DefaultHelper;
        if (DefaultPtr)
            DefaultHelper = MakeUnique<FScriptArrayHelper>(ArrayProperty, const_cast<void*>(DefaultPtr));
        const int32 Limit = FMath::Min(Helper.Num(), MaxContainerElements);
        if (Helper.Num() > Limit) ++Counts.ContainerElementLimitHits;
        for (int32 Index = 0; Index < Limit; ++Index)
        {
            const void* ElementPtr = Helper.GetRawPtr(Index);
            const void* ElementDefaultPtr = DefaultHelper.IsValid() && Index < DefaultHelper->Num()
                ? DefaultHelper->GetRawPtr(Index)
                : nullptr;
            if (!WritePropertyRecursive(
                    ArrayProperty->Inner, ElementPtr, ElementDefaultPtr, ExportOwner, DefaultExportOwner,
                    AssetPath, OwnerPath, OwnerKind, OwnerType, RootProperty,
                    FString::Printf(TEXT("%s[%d]"), *PropertyPath, Index),
                    Depth + 1, PropertyWriter, ReferenceWriter, State, Counts,
                    PropertyCount, ReferenceCount))
            {
                return false;
            }
        }
    }
    else if (const FSetProperty* SetProperty = CastField<FSetProperty>(Property))
    {
        FScriptSetHelper Helper(SetProperty, const_cast<void*>(ValuePtr));
        int32 Written = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && Written < MaxContainerElements; ++Index)
        {
            if (!Helper.IsValidIndex(Index)) continue;
            if (!WritePropertyRecursive(
                    SetProperty->ElementProp, Helper.GetElementPtr(Index), nullptr,
                    ExportOwner, DefaultExportOwner, AssetPath, OwnerPath, OwnerKind, OwnerType,
                    RootProperty, FString::Printf(TEXT("%s{%d}"), *PropertyPath, Written),
                    Depth + 1, PropertyWriter, ReferenceWriter, State, Counts,
                    PropertyCount, ReferenceCount))
            {
                return false;
            }
            ++Written;
        }
        if (Helper.Num() > Written) ++Counts.ContainerElementLimitHits;
    }
    else if (const FMapProperty* MapProperty = CastField<FMapProperty>(Property))
    {
        FScriptMapHelper Helper(MapProperty, const_cast<void*>(ValuePtr));
        int32 Written = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && Written < MaxContainerElements; ++Index)
        {
            if (!Helper.IsValidIndex(Index)) continue;
            if (!WritePropertyRecursive(
                    MapProperty->KeyProp, Helper.GetKeyPtr(Index), nullptr,
                    ExportOwner, DefaultExportOwner, AssetPath, OwnerPath, OwnerKind, OwnerType,
                    RootProperty, FString::Printf(TEXT("%s{%d}.Key"), *PropertyPath, Written),
                    Depth + 1, PropertyWriter, ReferenceWriter, State, Counts,
                    PropertyCount, ReferenceCount))
            {
                return false;
            }
            if (!WritePropertyRecursive(
                    MapProperty->ValueProp, Helper.GetValuePtr(Index), nullptr,
                    ExportOwner, DefaultExportOwner, AssetPath, OwnerPath, OwnerKind, OwnerType,
                    RootProperty, FString::Printf(TEXT("%s{%d}.Value"), *PropertyPath, Written),
                    Depth + 1, PropertyWriter, ReferenceWriter, State, Counts,
                    PropertyCount, ReferenceCount))
            {
                return false;
            }
            ++Written;
        }
        if (Helper.Num() > Written) ++Counts.ContainerElementLimitHits;
    }

    return true;
}

static bool WriteObjectProperties(
    UObject* Object,
    const FString& AssetPath,
    const FString& OwnerKind,
    FJsonlWriter& PropertyWriter,
    FJsonlWriter& ReferenceWriter,
    FCounts& Counts,
    int64& PropertyCount,
    int64& ReferenceCount)
{
    if (!Object) return true;
    UObject* DefaultObject = Object->GetClass() ? Object->GetClass()->GetDefaultObject() : nullptr;
    FOwnerState State;
    TSet<FString> Seen;

    for (UClass* Class = Object->GetClass(); Class && Class != UObject::StaticClass(); Class = Class->GetSuperClass())
    {
        for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
        {
            const FProperty* Property = *It;
            if (!ShouldInspectProperty(Property)) continue;
            const FString Key = Class->GetPathName() + TEXT("::") + Property->GetName();
            if (Seen.Contains(Key)) continue;
            Seen.Add(Key);

            for (int32 StaticIndex = 0; StaticIndex < Property->ArrayDim; ++StaticIndex)
            {
                const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object, StaticIndex);
                const void* DefaultPtr = DefaultObject
                    ? Property->ContainerPtrToValuePtr<void>(DefaultObject, StaticIndex)
                    : nullptr;
                FString Path = Property->GetName();
                if (Property->ArrayDim > 1)
                    Path += FString::Printf(TEXT("[%d]"), StaticIndex);
                if (!WritePropertyRecursive(
                        Property, ValuePtr, DefaultPtr, Object, DefaultObject,
                        AssetPath, Object->GetPathName(), OwnerKind, Object->GetClass()->GetPathName(),
                        Property->GetName(), Path, 0,
                        PropertyWriter, ReferenceWriter, State, Counts,
                        PropertyCount, ReferenceCount))
                {
                    return false;
                }
            }
        }
    }
    return true;
}

static TSharedRef<FJsonObject> SelectedRegistryTags(const FAssetData& Asset)
{
    TSharedRef<FJsonObject> Tags = MakeShared<FJsonObject>();
    for (const TCHAR* Name : RegistryTagNames)
    {
        FString Value;
        if (Asset.GetTagValue(FName(Name), Value))
        {
            Tags->SetStringField(Name, Value);
        }
    }
    return Tags;
}

static bool WriteAsset(
    const FAssetData& Asset,
    UObject* Object,
    FWriters& Writers,
    FCounts& Counts)
{
    if (!Object) return false;
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    const FString ClassPath = Asset.AssetClassPath.ToString();
    const FString Kind = AssetKind(ClassPath);

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), AssetPath);
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("asset_name"), Asset.AssetName.ToString());
    Row->SetStringField(TEXT("class_path"), ClassPath);
    Row->SetStringField(TEXT("asset_kind"), Kind);
    Row->SetStringField(TEXT("loaded_class"), Object->GetClass()->GetPathName());
    Row->SetBoolField(TEXT("loaded"), true);
    Row->SetObjectField(TEXT("registry_tags"), SelectedRegistryTags(Asset));
    if (!Writers.Assets.Write(Row)) return false;

    ++Counts.LoadedAssets;
    if (Kind == TEXT("skeletal_mesh")) ++Counts.SkeletalMeshes;
    else if (Kind == TEXT("physics_asset")) ++Counts.PhysicsAssets;

    if (!WriteObjectProperties(
            Object, AssetPath, Kind,
            Writers.AssetProperties, Writers.AssetReferences,
            Counts, Counts.AssetProperties, Counts.AssetReferences))
    {
        return false;
    }

    TArray<UObject*> Owned;
    GetObjectsWithOuter(Object, Owned, EGetObjectsFlags::IncludeNestedObjects);
    Owned.Sort([](const UObject& A, const UObject& B)
    {
        return FCString::Strcmp(*A.GetPathName(), *B.GetPathName()) < 0;
    });

    for (UObject* Child : Owned)
    {
        if (!Child || Child == Object || Child->HasAnyFlags(RF_Transient | RF_ClassDefaultObject)) continue;
        TSharedRef<FJsonObject> ChildRow = MakeShared<FJsonObject>();
        ChildRow->SetStringField(TEXT("asset_path"), AssetPath);
        ChildRow->SetStringField(TEXT("object_path"), Child->GetPathName());
        ChildRow->SetStringField(TEXT("class_path"), Child->GetClass()->GetPathName());
        ChildRow->SetStringField(TEXT("outer_path"), Child->GetOuter() ? Child->GetOuter()->GetPathName() : FString());
        if (!Writers.OwnedObjects.Write(ChildRow)) return false;
        ++Counts.OwnedObjects;

        if (!WriteObjectProperties(
                Child, AssetPath, TEXT("owned_object"),
                Writers.OwnedObjectProperties, Writers.OwnedObjectReferences,
                Counts, Counts.OwnedObjectProperties, Counts.OwnedObjectReferences))
        {
            return false;
        }
    }

    return true;
}

static bool WriteManifest(const FString& OutputDir, const FCounts& Counts, bool bSuccess, const FString& Error, bool bIncludeEngine)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetNumberField(TEXT("schema_version"), SchemaVersion);
    Root->SetBoolField(TEXT("success"), bSuccess);
    Root->SetStringField(TEXT("error"), Error);
    Root->SetBoolField(TEXT("diagnostic_only"), true);
    Root->SetBoolField(TEXT("semantic_promotion"), false);
    Root->SetBoolField(TEXT("schema_promotion"), false);
    Root->SetBoolField(TEXT("runtime_state_captured"), false);
    Root->SetBoolField(TEXT("render_buffers_captured"), false);
    Root->SetBoolField(TEXT("cloth_simulation_state_captured"), false);
    Root->SetBoolField(TEXT("chaos_runtime_state_captured"), false);
    Root->SetBoolField(TEXT("maps_loaded"), false);
    Root->SetBoolField(TEXT("include_engine"), bIncludeEngine);
    Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetStringField(TEXT("capture_scope"), TEXT("exact project SkeletalMesh and PhysicsAsset assets, recursively reflected authored properties/references, and owned UObject topology only; no maps, runtime skinning, render buffers, cloth simulation or Chaos runtime state"));

    TSharedRef<FJsonObject> CountObject = MakeShared<FJsonObject>();
    CountObject->SetNumberField(TEXT("registry_candidates"), Counts.RegistryCandidates);
    CountObject->SetNumberField(TEXT("loaded_assets"), Counts.LoadedAssets);
    CountObject->SetNumberField(TEXT("load_failures"), Counts.LoadFailures);
    CountObject->SetNumberField(TEXT("skeletal_meshes"), Counts.SkeletalMeshes);
    CountObject->SetNumberField(TEXT("physics_assets"), Counts.PhysicsAssets);
    CountObject->SetNumberField(TEXT("asset_properties"), Counts.AssetProperties);
    CountObject->SetNumberField(TEXT("asset_references"), Counts.AssetReferences);
    CountObject->SetNumberField(TEXT("owned_objects"), Counts.OwnedObjects);
    CountObject->SetNumberField(TEXT("owned_object_properties"), Counts.OwnedObjectProperties);
    CountObject->SetNumberField(TEXT("owned_object_references"), Counts.OwnedObjectReferences);
    CountObject->SetNumberField(TEXT("truncated_properties"), Counts.TruncatedProperties);
    CountObject->SetNumberField(TEXT("property_depth_limit_hits"), Counts.PropertyDepthLimitHits);
    CountObject->SetNumberField(TEXT("property_row_limit_hits"), Counts.PropertyRowLimitHits);
    CountObject->SetNumberField(TEXT("container_element_limit_hits"), Counts.ContainerElementLimitHits);
    Root->SetObjectField(TEXT("counts"), CountObject);

    TArray<TSharedPtr<FJsonValue>> Files;
    static const TCHAR* Names[] = {
        TEXT("skeletalmesh_physicsasset_assets.jsonl"),
        TEXT("skeletalmesh_physicsasset_asset_properties.jsonl"),
        TEXT("skeletalmesh_physicsasset_asset_references.jsonl"),
        TEXT("skeletalmesh_physicsasset_owned_objects.jsonl"),
        TEXT("skeletalmesh_physicsasset_owned_object_properties.jsonl"),
        TEXT("skeletalmesh_physicsasset_owned_object_references.jsonl"),
    };
    for (const TCHAR* Name : Names)
        Files.Add(MakeShared<FJsonValueString>(Name));
    Root->SetArrayField(TEXT("files"), Files);

    FString Text;
    const TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer =
        TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Text);
    if (!FJsonSerializer::Serialize(Root, Writer)) return false;
    return FFileHelper::SaveStringToFile(
        Text,
        *FPaths::Combine(OutputDir, TEXT("skeletalmesh_physicsasset_capture_manifest.json")),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

static bool RunCapture(const FString& OutputDir, bool bIncludeEngine, FCounts& Counts, FString& OutError)
{
    FWriters Writers;
    if (!Writers.Open(OutputDir))
    {
        OutError = TEXT("could not open focused capture writers");
        return false;
    }

    FAssetRegistryModule& AssetRegistryModule =
        FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
    IAssetRegistry& Registry = AssetRegistryModule.Get();
    Registry.SearchAllAssets(true);

    TArray<FAssetData> Assets;
    Registry.GetAllAssets(Assets, true);
    Assets.Sort([](const FAssetData& A, const FAssetData& B)
    {
        const FString APath = A.GetSoftObjectPath().ToString();
        const FString BPath = B.GetSoftObjectPath().ToString();
        return FCString::Strcmp(*APath, *BPath) < 0;
    });

    const FString ProjectDir = NormalizeAbsolutePath(FPaths::ProjectDir());
    for (const FAssetData& Asset : Assets)
    {
        const FString ClassPath = Asset.AssetClassPath.ToString();
        if (!IsFocusClass(ClassPath)) continue;
        if (!AssetInScope(Asset, ProjectDir, bIncludeEngine)) continue;
        ++Counts.RegistryCandidates;

        UObject* Object = Asset.GetAsset();
        if (!Object)
        {
            ++Counts.LoadFailures;
            continue;
        }
        if (!Object->GetClass()->GetPathName().Equals(ClassPath, ESearchCase::CaseSensitive))
        {
            OutError = TEXT("loaded class mismatch for ") + Asset.GetSoftObjectPath().ToString();
            Writers.Close();
            return false;
        }
        if (!WriteAsset(Asset, Object, Writers, Counts))
        {
            OutError = TEXT("failed while writing focused asset ") + Asset.GetSoftObjectPath().ToString();
            Writers.Close();
            return false;
        }
    }

    if (!Writers.Close())
    {
        OutError = TEXT("failed closing focused capture writers");
        return false;
    }
    return true;
}
} // namespace UnrealAssetToolSkeletalMeshPhysicsAsset

UUnrealAssetToolSkeletalMeshPhysicsAssetCommandlet::UUnrealAssetToolSkeletalMeshPhysicsAssetCommandlet()
{
    IsClient = false;
    IsEditor = true;
    LogToConsole = true;
    ShowErrorCount = true;
}

int32 UUnrealAssetToolSkeletalMeshPhysicsAssetCommandlet::Main(const FString& Params)
{
    using namespace UnrealAssetToolSkeletalMeshPhysicsAsset;

    FString OutputDir;
    FParse::Value(*Params, TEXT("Output="), OutputDir);
    if (OutputDir.IsEmpty())
        OutputDir = FPaths::Combine(FPaths::ProjectDir(), TEXT(".uatool"), TEXT("skeletalmesh-physicsasset-native-capture"));
    else if (FPaths::IsRelative(OutputDir))
        OutputDir = FPaths::Combine(FPaths::ProjectDir(), OutputDir);
    OutputDir = NormalizeAbsolutePath(OutputDir);
    IFileManager::Get().MakeDirectory(*OutputDir, true);

    const bool bIncludeEngine = FParse::Param(*Params, TEXT("IncludeEngine"));
    FCounts Counts;
    FString Error;
    const bool bSuccess = RunCapture(OutputDir, bIncludeEngine, Counts, Error);
    if (!WriteManifest(OutputDir, Counts, bSuccess, Error, bIncludeEngine))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolSkeletalMeshPhysicsAsset: failed writing capture manifest"));
        return 2;
    }
    if (!bSuccess)
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolSkeletalMeshPhysicsAsset: %s"), *Error);
        return 1;
    }

    UE_LOG(
        LogTemp,
        Display,
        TEXT("UnrealAssetToolSkeletalMeshPhysicsAsset captured %lld meshes, %lld physics assets, %lld owned objects, %lld asset properties, %lld owned properties"),
        Counts.SkeletalMeshes,
        Counts.PhysicsAssets,
        Counts.OwnedObjects,
        Counts.AssetProperties,
        Counts.OwnedObjectProperties);
    return Counts.LoadFailures == 0 ? 0 : 3;
}

#include "UnrealAssetToolGASCommandlet.h"

#include "AssetRegistry/AssetData.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Engine/Blueprint.h"
#include "HAL/FileManager.h"
#include "Json.h"
#include "Misc/App.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/SoftObjectPtr.h"
#include "UObject/UObjectHash.h"
#include "UObject/UObjectIterator.h"
#include "UObject/UnrealType.h"

namespace UnrealAssetToolGAS
{
constexpr int32 SchemaVersion = 1;
constexpr int32 MaxExportChars = 65536;
constexpr int32 MaxReferenceDepth = 8;
constexpr int32 MaxReferencesPerRoot = 4096;
constexpr int32 MaxNestedObjectsPerSubject = 4096;

struct FCounts
{
    int64 AssetsConsidered = 0;
    int64 CandidateAssets = 0;
    int64 LoadedAssets = 0;
    int64 Assets = 0;
    int64 Classes = 0;
    int64 Properties = 0;
    int64 References = 0;
    int64 NestedObjects = 0;
    int64 TruncatedProperties = 0;
    TMap<FString, int64> KindCounts;
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
    FJsonlWriter Classes;
    FJsonlWriter Properties;
    FJsonlWriter References;

    bool Open(const FString& OutputDir)
    {
        return Assets.Open(FPaths::Combine(OutputDir, TEXT("gas_assets.jsonl"))) &&
            Classes.Open(FPaths::Combine(OutputDir, TEXT("gas_classes.jsonl"))) &&
            Properties.Open(FPaths::Combine(OutputDir, TEXT("gas_properties.jsonl"))) &&
            References.Open(FPaths::Combine(OutputDir, TEXT("gas_references.jsonl")));
    }

    bool Close()
    {
        const bool A = Assets.Close();
        const bool B = Classes.Close();
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

static FString ClassifyClass(const UClass* Class)
{
    if (!Class)
    {
        return FString();
    }
    if (ClassInheritsName(Class, TEXT("GameplayAbility"))) return TEXT("gameplay_ability");
    if (ClassInheritsName(Class, TEXT("GameplayEffect"))) return TEXT("gameplay_effect");
    if (ClassInheritsName(Class, TEXT("GameplayEffectComponent"))) return TEXT("gameplay_effect_component");
    if (ClassInheritsName(Class, TEXT("AbilitySystemComponent"))) return TEXT("ability_system_component");
    if (ClassInheritsName(Class, TEXT("AttributeSet"))) return TEXT("attribute_set");
    if (ClassInheritsName(Class, TEXT("AbilityTask"))) return TEXT("ability_task");
    if (ClassInheritsName(Class, TEXT("GameplayCueNotify_Actor")) ||
        ClassInheritsName(Class, TEXT("GameplayCueNotify_Static")) ||
        ClassInheritsName(Class, TEXT("GameplayCueNotify")))
    {
        return TEXT("gameplay_cue");
    }
    if (ClassInheritsName(Class, TEXT("GameplayEffectCalculation")) ||
        ClassInheritsName(Class, TEXT("GameplayModMagnitudeCalculation")) ||
        ClassInheritsName(Class, TEXT("GameplayEffectExecutionCalculation")) ||
        ClassInheritsName(Class, TEXT("GameplayEffectCustomApplicationRequirement")))
    {
        return TEXT("gameplay_effect_calculation");
    }
    if (ClassInheritsName(Class, TEXT("LyraAbilitySet"))) return TEXT("ability_set");
    if (ClassInheritsName(Class, TEXT("LyraGameplayTagRelationshipMapping"))) return TEXT("tag_relationship");
    if (ClassInheritsName(Class, TEXT("GameFeatureAction_AddAbilities"))) return TEXT("game_feature_grant");
    if (ClassInheritsName(Class, TEXT("GameplayTagResponseTable"))) return TEXT("tag_response_table");
    return FString();
}

static FString ClassifyMetadata(const FString& Text)
{
    const FString Lower = Text.ToLower();
    if (Lower.Contains(TEXT("gamefeatureaction_addabilities"))) return TEXT("game_feature_grant");
    if (Lower.Contains(TEXT("lyragameplaytagrelationshipmapping"))) return TEXT("tag_relationship");
    if (Lower.Contains(TEXT("lyraabilityset"))) return TEXT("ability_set");
    if (Lower.Contains(TEXT("abilitysystemcomponent"))) return TEXT("ability_system_component");
    if (Lower.Contains(TEXT("attributeset")) || Lower.Contains(TEXT("lyrahealthset")) || Lower.Contains(TEXT("lyracombatset"))) return TEXT("attribute_set");
    if (Lower.Contains(TEXT("gameplayeffectcomponent"))) return TEXT("gameplay_effect_component");
    if (Lower.Contains(TEXT("gameplayeffectexecutioncalculation")) || Lower.Contains(TEXT("gameplaymodmagnitudecalculation")) || Lower.Contains(TEXT("gameplayeffectcustomapplicationrequirement"))) return TEXT("gameplay_effect_calculation");
    if (Lower.Contains(TEXT("gameplayeffect"))) return TEXT("gameplay_effect");
    if (Lower.Contains(TEXT("gameplaycuenotify")) || Lower.Contains(TEXT("gameplaycueset"))) return TEXT("gameplay_cue");
    if (Lower.Contains(TEXT("abilitytask"))) return TEXT("ability_task");
    if (Lower.Contains(TEXT("gameplayability"))) return TEXT("gameplay_ability");
    if (Lower.Contains(TEXT("gameplaytagresponsetable"))) return TEXT("tag_response_table");
    return TEXT("gas_other");
}

static bool ContainsCandidateAnchor(const FString& Text)
{
    const FString Lower = Text.ToLower();
    static const TCHAR* Anchors[] = {
        TEXT("/script/gameplayabilities"), TEXT("gameplayability"),
        TEXT("abilitysystemcomponent"), TEXT("attributeset"), TEXT("gameplayeffect"),
        TEXT("gameplaycuenotify"), TEXT("gameplaycueset"), TEXT("abilitytask"),
        TEXT("gameplaymodmagnitudecalculation"), TEXT("gameplayeffectexecutioncalculation"),
        TEXT("gameplayeffectcustomapplicationrequirement"), TEXT("gameplaytagresponsetable"),
        TEXT("lyraabilityset"), TEXT("lyragameplayability"), TEXT("lyraabilitysystemcomponent"),
        TEXT("lyraattributeset"), TEXT("lyrahealthset"), TEXT("lyracombatset"),
        TEXT("lyragameplaytagrelationshipmapping"), TEXT("gamefeatureaction_addabilities")
    };
    for (const TCHAR* Anchor : Anchors)
    {
        if (Lower.Contains(Anchor))
        {
            return true;
        }
    }
    return false;
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
    Parts.Reserve(7);
    Parts.Add(Asset.GetSoftObjectPath().ToString());
    Parts.Add(Asset.PackageName.ToString());
    Parts.Add(Asset.AssetName.ToString());
    Parts.Add(Asset.AssetClassPath.ToString());
    Parts.Add(AssetTag(Asset, TEXT("ParentClass")));
    Parts.Add(AssetTag(Asset, TEXT("NativeParentClass")));
    Parts.Add(AssetTag(Asset, TEXT("GeneratedClass")));
    return FString::Join(Parts, TEXT("\n"));
}

static FString ExportProperty(const FProperty* Property, const void* ValuePtr, UObject* Owner, bool& bTruncated)
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

struct FReferenceContext
{
    FString SourcePath;
    FString OwnerPath;
    FString OwnerKind;
    FString GASKind;
    FString RootProperty;
    int32 Rows = 0;
    FWriters* Writers = nullptr;
    FCounts* Counts = nullptr;
};

static void EmitReference(
    FReferenceContext& Context,
    const FString& PropertyPath,
    const FString& ReferenceKind,
    const FString& TargetPath,
    const FString& TargetClass)
{
    if (!Context.Writers || !Context.Counts || TargetPath.IsEmpty() || Context.Rows >= MaxReferencesPerRoot)
    {
        return;
    }
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("source_path"), Context.SourcePath);
    Row->SetStringField(TEXT("owner_path"), Context.OwnerPath);
    Row->SetStringField(TEXT("owner_kind"), Context.OwnerKind);
    Row->SetStringField(TEXT("gas_kind"), Context.GASKind);
    Row->SetStringField(TEXT("root_property"), Context.RootProperty);
    Row->SetStringField(TEXT("property_path"), PropertyPath);
    Row->SetStringField(TEXT("reference_kind"), ReferenceKind);
    Row->SetStringField(TEXT("target_path"), TargetPath);
    Row->SetStringField(TEXT("target_class"), TargetClass);
    if (Context.Writers->References.Write(Row))
    {
        ++Context.Rows;
        ++Context.Counts->References;
    }
}

static void CollectReferences(
    const FProperty* Property,
    const void* ValuePtr,
    const FString& PropertyPath,
    int32 Depth,
    FReferenceContext& Context)
{
    if (!Property || !ValuePtr || Depth > MaxReferenceDepth || Context.Rows >= MaxReferencesPerRoot)
    {
        return;
    }
    if (const FSoftObjectProperty* SoftProperty = CastField<FSoftObjectProperty>(Property))
    {
        const FSoftObjectPtr* SoftPtr = static_cast<const FSoftObjectPtr*>(ValuePtr);
        if (SoftPtr && !SoftPtr->IsNull())
        {
            EmitReference(Context, PropertyPath, TEXT("soft_object"), SoftPtr->ToSoftObjectPath().ToString(), FString());
        }
        return;
    }
    if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
    {
        UObject* Target = ObjectProperty->GetObjectPropertyValue(ValuePtr);
        if (Target)
        {
            EmitReference(Context, PropertyPath, TEXT("hard_object"), Target->GetPathName(), Target->GetClass()->GetPathName());
        }
        return;
    }
    if (const FStructProperty* StructProperty = CastField<FStructProperty>(Property))
    {
        if (!StructProperty->Struct) return;
        for (TFieldIterator<FProperty> It(StructProperty->Struct); It; ++It)
        {
            const FProperty* Inner = *It;
            if (!ShouldInspectProperty(Inner)) continue;
            for (int32 StaticIndex = 0; StaticIndex < Inner->ArrayDim; ++StaticIndex)
            {
                const void* InnerValue = Inner->ContainerPtrToValuePtr<void>(ValuePtr, StaticIndex);
                const FString Child = PropertyPath + TEXT(".") + Inner->GetName() +
                    (Inner->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
                CollectReferences(Inner, InnerValue, Child, Depth + 1, Context);
            }
        }
        return;
    }
    if (const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
    {
        FScriptArrayHelper Helper(ArrayProperty, ValuePtr);
        const int32 Limit = FMath::Min(Helper.Num(), 4096);
        for (int32 Index = 0; Index < Limit && Context.Rows < MaxReferencesPerRoot; ++Index)
        {
            CollectReferences(
                ArrayProperty->Inner,
                Helper.GetRawPtr(Index),
                FString::Printf(TEXT("%s[%d]"), *PropertyPath, Index),
                Depth + 1,
                Context);
        }
        return;
    }
    if (const FSetProperty* SetProperty = CastField<FSetProperty>(Property))
    {
        FScriptSetHelper Helper(SetProperty, ValuePtr);
        int32 Emitted = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && Emitted < 4096 && Context.Rows < MaxReferencesPerRoot; ++Index)
        {
            if (!Helper.IsValidIndex(Index)) continue;
            CollectReferences(
                SetProperty->ElementProp,
                Helper.GetElementPtr(Index),
                FString::Printf(TEXT("%s{%d}"), *PropertyPath, Emitted++),
                Depth + 1,
                Context);
        }
        return;
    }
    if (const FMapProperty* MapProperty = CastField<FMapProperty>(Property))
    {
        FScriptMapHelper Helper(MapProperty, ValuePtr);
        int32 Emitted = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && Emitted < 4096 && Context.Rows < MaxReferencesPerRoot; ++Index)
        {
            if (!Helper.IsValidIndex(Index)) continue;
            const FString Base = FString::Printf(TEXT("%s{%d}"), *PropertyPath, Emitted++);
            CollectReferences(MapProperty->KeyProp, Helper.GetKeyPtr(Index), Base + TEXT(".key"), Depth + 1, Context);
            CollectReferences(MapProperty->ValueProp, Helper.GetValuePtr(Index), Base + TEXT(".value"), Depth + 1, Context);
        }
    }
}

static bool WriteState(
    UObject* Object,
    const FString& SourcePath,
    const FString& OwnerKind,
    const FString& GASKind,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenOwners)
{
    if (!Object)
    {
        return true;
    }
    const FString OwnerPath = Object->GetPathName();
    if (SeenOwners.Contains(OwnerPath))
    {
        return true;
    }
    SeenOwners.Add(OwnerPath);

    TSet<FString> SeenProperties;
    for (UClass* Class = Object->GetClass(); Class && Class != UObject::StaticClass(); Class = Class->GetSuperClass())
    {
        for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
        {
            FProperty* Property = *It;
            if (!ShouldInspectProperty(Property)) continue;
            const FString PropertyKey = Class->GetPathName() + TEXT("::") + Property->GetName();
            if (SeenProperties.Contains(PropertyKey)) continue;
            SeenProperties.Add(PropertyKey);

            bool bTruncated = false;
            const FString Value = ExportProperty(
                Property,
                Property->ContainerPtrToValuePtr<void>(Object),
                Object,
                bTruncated);
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("source_path"), SourcePath);
            Row->SetStringField(TEXT("owner_path"), OwnerPath);
            Row->SetStringField(TEXT("owner_kind"), OwnerKind);
            Row->SetStringField(TEXT("gas_kind"), GASKind);
            Row->SetStringField(TEXT("owner_class"), Object->GetClass()->GetPathName());
            Row->SetStringField(TEXT("declaring_type"), Class->GetPathName());
            Row->SetStringField(TEXT("property_name"), Property->GetName());
            Row->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
            Row->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
            Row->SetStringField(TEXT("value"), Value);
            Row->SetBoolField(TEXT("truncated"), bTruncated);
            if (!Writers.Properties.Write(Row)) return false;
            ++Counts.Properties;
            if (bTruncated) ++Counts.TruncatedProperties;

            FReferenceContext Context;
            Context.SourcePath = SourcePath;
            Context.OwnerPath = OwnerPath;
            Context.OwnerKind = OwnerKind;
            Context.GASKind = GASKind;
            Context.RootProperty = Property->GetName();
            Context.Writers = &Writers;
            Context.Counts = &Counts;
            for (int32 StaticIndex = 0; StaticIndex < Property->ArrayDim; ++StaticIndex)
            {
                const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object, StaticIndex);
                const FString Path = Property->GetName() +
                    (Property->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
                CollectReferences(Property, ValuePtr, Path, 0, Context);
            }
        }
    }
    return true;
}

static bool ShouldCaptureNested(UObject* Object)
{
    if (!Object) return false;
    const FString Kind = ClassifyClass(Object->GetClass());
    if (!Kind.IsEmpty()) return true;
    return Object->GetClass()->GetName().Contains(TEXT("GameplayEffectComponent"), ESearchCase::IgnoreCase);
}

static bool WriteNestedState(
    UObject* Root,
    const FString& SourcePath,
    const FString& RootKind,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenOwners)
{
    if (!Root) return true;
    TArray<UObject*> Nested;
    GetObjectsWithOuter(
        Root,
        Nested,
        EGetObjectsFlags::IncludeNestedObjects,
        RF_Transient,
        EInternalObjectFlags::Garbage);
    Nested.Sort([](const UObject& A, const UObject& B)
    {
        return A.GetPathName() < B.GetPathName();
    });
    const int32 Limit = FMath::Min(Nested.Num(), MaxNestedObjectsPerSubject);
    for (int32 Index = 0; Index < Limit; ++Index)
    {
        UObject* Object = Nested[Index];
        if (!ShouldCaptureNested(Object)) continue;
        FString Kind = ClassifyClass(Object->GetClass());
        if (Kind.IsEmpty()) Kind = RootKind;
        const bool bWasSeen = SeenOwners.Contains(Object->GetPathName());
        if (!WriteState(Object, SourcePath, TEXT("nested_object"), Kind, Writers, Counts, SeenOwners)) return false;
        if (!bWasSeen) ++Counts.NestedObjects;
    }
    return true;
}

static bool WriteAsset(
    const FAssetData& Asset,
    UObject* Object,
    const FString& Metadata,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenOwners,
    FString& OutError)
{
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    UBlueprint* Blueprint = Cast<UBlueprint>(Object);
    UClass* SubjectClass = Blueprint && Blueprint->GeneratedClass
        ? Blueprint->GeneratedClass.Get()
        : (Object ? Object->GetClass() : nullptr);
    FString Kind = ClassifyClass(SubjectClass);
    if (Kind.IsEmpty()) Kind = ClassifyMetadata(Metadata);

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), AssetPath);
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("asset_name"), Asset.AssetName.ToString());
    Row->SetStringField(TEXT("asset_class"), Asset.AssetClassPath.ToString());
    Row->SetStringField(TEXT("parent_class_tag"), AssetTag(Asset, TEXT("ParentClass")));
    Row->SetStringField(TEXT("native_parent_class_tag"), AssetTag(Asset, TEXT("NativeParentClass")));
    Row->SetStringField(TEXT("generated_class_tag"), AssetTag(Asset, TEXT("GeneratedClass")));
    Row->SetStringField(TEXT("loaded_object_class"), Object ? Object->GetClass()->GetPathName() : FString());
    Row->SetStringField(
        TEXT("generated_class"),
        Blueprint && Blueprint->GeneratedClass ? Blueprint->GeneratedClass->GetPathName() : FString());
    Row->SetStringField(TEXT("gas_kind"), Kind);
    Row->SetBoolField(TEXT("loaded"), Object != nullptr);
    Row->SetStringField(TEXT("provenance"), TEXT("asset_registry_candidate_plus_loaded_object_reflection"));
    if (!Writers.Assets.Write(Row))
    {
        OutError = TEXT("failed writing GAS asset row: ") + AssetPath;
        return false;
    }
    ++Counts.Assets;
    ++Counts.KindCounts.FindOrAdd(Kind);

    if (!Object) return true;
    if (!WriteState(Object, AssetPath, TEXT("asset_object"), Kind, Writers, Counts, SeenOwners))
    {
        OutError = TEXT("failed writing GAS asset object state: ") + AssetPath;
        return false;
    }
    if (!WriteNestedState(Object, AssetPath, Kind, Writers, Counts, SeenOwners))
    {
        OutError = TEXT("failed writing nested GAS asset state: ") + AssetPath;
        return false;
    }

    if (Blueprint && Blueprint->GeneratedClass)
    {
        UObject* CDO = Blueprint->GeneratedClass->GetDefaultObject(false);
        if (CDO)
        {
            if (!WriteState(CDO, AssetPath, TEXT("blueprint_cdo"), Kind, Writers, Counts, SeenOwners) ||
                !WriteNestedState(CDO, AssetPath, Kind, Writers, Counts, SeenOwners))
            {
                OutError = TEXT("failed writing GAS Blueprint CDO state: ") + AssetPath;
                return false;
            }
        }
    }
    return true;
}

static bool WriteClass(
    UClass* Class,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenClasses,
    TSet<FString>& SeenOwners,
    FString& OutError)
{
    if (!Class) return true;
    const FString ClassPath = Class->GetPathName();
    if (SeenClasses.Contains(ClassPath)) return true;
    const FString Kind = ClassifyClass(Class);
    if (Kind.IsEmpty()) return true;
    SeenClasses.Add(ClassPath);

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("class_path"), ClassPath);
    Row->SetStringField(TEXT("class_name"), Class->GetName());
    Row->SetStringField(TEXT("super_class"), Class->GetSuperClass() ? Class->GetSuperClass()->GetPathName() : FString());
    Row->SetStringField(TEXT("gas_kind"), Kind);
    Row->SetBoolField(TEXT("native"), Class->HasAnyClassFlags(CLASS_Native));
    UObject* CDO = Class->GetDefaultObject(false);
    Row->SetStringField(TEXT("cdo_path"), CDO ? CDO->GetPathName() : FString());
    Row->SetStringField(TEXT("provenance"), TEXT("loaded_class_reflection"));
    if (!Writers.Classes.Write(Row))
    {
        OutError = TEXT("failed writing GAS class row: ") + ClassPath;
        return false;
    }
    ++Counts.Classes;

    if (CDO)
    {
        if (!WriteState(CDO, ClassPath, TEXT("class_cdo"), Kind, Writers, Counts, SeenOwners) ||
            !WriteNestedState(CDO, ClassPath, Kind, Writers, Counts, SeenOwners))
        {
            OutError = TEXT("failed writing GAS class CDO state: ") + ClassPath;
            return false;
        }
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
    Root->SetStringField(TEXT("schema_name"), TEXT("gas_capture"));
    Root->SetStringField(TEXT("pass"), TEXT("UnrealAssetToolGAS"));
    Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetStringField(TEXT("project_name"), FApp::GetProjectName());
    Root->SetBoolField(TEXT("success"), bSuccess);
    Root->SetStringField(TEXT("error"), Error);
    Root->SetBoolField(TEXT("diagnostic_only"), true);
    Root->SetBoolField(TEXT("semantic_promotion"), false);
    Root->SetBoolField(TEXT("runtime_state_captured"), false);
    Root->SetStringField(TEXT("provenance"), TEXT("asset_registry_candidate_plus_loaded_object_reflection"));

    TSharedRef<FJsonObject> CountsJson = MakeShared<FJsonObject>();
    CountsJson->SetNumberField(TEXT("assets_considered"), Counts.AssetsConsidered);
    CountsJson->SetNumberField(TEXT("candidate_assets"), Counts.CandidateAssets);
    CountsJson->SetNumberField(TEXT("loaded_assets"), Counts.LoadedAssets);
    CountsJson->SetNumberField(TEXT("gas_assets"), Counts.Assets);
    CountsJson->SetNumberField(TEXT("gas_classes"), Counts.Classes);
    CountsJson->SetNumberField(TEXT("gas_properties"), Counts.Properties);
    CountsJson->SetNumberField(TEXT("gas_references"), Counts.References);
    CountsJson->SetNumberField(TEXT("nested_objects"), Counts.NestedObjects);
    CountsJson->SetNumberField(TEXT("truncated_properties"), Counts.TruncatedProperties);
    Root->SetObjectField(TEXT("counts"), CountsJson);

    TSharedRef<FJsonObject> Kinds = MakeShared<FJsonObject>();
    TArray<FString> KindNames;
    Counts.KindCounts.GetKeys(KindNames);
    KindNames.Sort();
    for (const FString& Kind : KindNames)
    {
        const int64* Count = Counts.KindCounts.Find(Kind);
        Kinds->SetNumberField(Kind, Count ? *Count : 0);
    }
    Root->SetObjectField(TEXT("asset_kind_counts"), Kinds);

    TArray<TSharedPtr<FJsonValue>> Files;
    Files.Add(MakeShared<FJsonValueString>(TEXT("gas_assets.jsonl")));
    Files.Add(MakeShared<FJsonValueString>(TEXT("gas_classes.jsonl")));
    Files.Add(MakeShared<FJsonValueString>(TEXT("gas_properties.jsonl")));
    Files.Add(MakeShared<FJsonValueString>(TEXT("gas_references.jsonl")));
    Root->SetArrayField(TEXT("files"), Files);

    FString Text;
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Text);
    if (!FJsonSerializer::Serialize(Root, Writer)) return false;
    Text.AppendChar(TEXT('\n'));
    return FFileHelper::SaveStringToFile(
        Text,
        *FPaths::Combine(OutputDir, TEXT("gas_capture_manifest.json")),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}
} // namespace UnrealAssetToolGAS

UUnrealAssetToolGASCommandlet::UUnrealAssetToolGASCommandlet()
{
    IsClient = false;
    IsEditor = true;
    IsServer = false;
    LogToConsole = true;
    ShowErrorCount = true;
}

int32 UUnrealAssetToolGASCommandlet::Main(const FString& Params)
{
    using namespace UnrealAssetToolGAS;

    FString OutputDir;
    if (!FParse::Value(*Params, TEXT("Output="), OutputDir))
    {
        OutputDir = FPaths::Combine(FPaths::ProjectDir(), TEXT(".uatool/gas-capture"));
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
        Error = TEXT("could not open one or more GAS capture JSONL writers");
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

        TSet<FString> SeenOwners;
        for (const FAssetData& Asset : Assets)
        {
            ++Counts.AssetsConsidered;
            const FString Package = Asset.PackageName.ToString();
            if (Package.StartsWith(TEXT("/Engine/"), ESearchCase::IgnoreCase))
            {
                continue;
            }
            const FString Metadata = CandidateText(Asset);
            if (!ContainsCandidateAnchor(Metadata))
            {
                continue;
            }
            ++Counts.CandidateAssets;
            UObject* Object = Asset.GetAsset();
            if (Object) ++Counts.LoadedAssets;
            if (!WriteAsset(Asset, Object, Metadata, Writers, Counts, SeenOwners, Error))
            {
                bSuccess = false;
                break;
            }
        }

        if (bSuccess)
        {
            TSet<FString> SeenClasses;
            for (TObjectIterator<UClass> It; It; ++It)
            {
                UClass* Class = *It;
                if (!Class || Class->HasAnyClassFlags(CLASS_Deprecated | CLASS_NewerVersionExists))
                {
                    continue;
                }
                if (!WriteClass(Class, Writers, Counts, SeenClasses, SeenOwners, Error))
                {
                    bSuccess = false;
                    break;
                }
            }
        }
    }

    // Synchronously finalize JSONL before publishing success. This preserves the
    // writer-lifetime invariant established during the City Sample schema-5 pass.
    if (!Writers.Close())
    {
        bSuccess = false;
        if (Error.IsEmpty()) Error = TEXT("failed closing one or more GAS capture writers");
    }

    if (!WriteManifest(OutputDir, Counts, bSuccess, Error))
    {
        UE_LOG(LogTemp, Error, TEXT("Could not write GAS capture manifest: %s"), *OutputDir);
        return 3;
    }
    if (!bSuccess)
    {
        UE_LOG(LogTemp, Error, TEXT("Focused GAS capture failed: %s"), *Error);
        return 4;
    }

    UE_LOG(
        LogTemp,
        Display,
        TEXT("Focused GAS capture complete: candidates=%lld loaded=%lld assets=%lld classes=%lld properties=%lld references=%lld runtime_state=false"),
        Counts.CandidateAssets,
        Counts.LoadedAssets,
        Counts.Assets,
        Counts.Classes,
        Counts.Properties,
        Counts.References);
    return 0;
}

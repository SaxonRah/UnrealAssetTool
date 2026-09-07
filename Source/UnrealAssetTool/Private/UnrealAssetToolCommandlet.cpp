#include "UnrealAssetToolCommandlet.h"
#include "UnrealAssetToolNativeScanner.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "AnimationConduitGraphSchema.h"
#include "AnimationGraph.h"
#include "AnimationStateGraph.h"
#include "AnimationStateMachineGraph.h"
#include "AnimationTransitionGraph.h"
#include "AnimGraphNode_LinkedAnimLayer.h"
#include "AnimGraphNode_LinkedInputPose.h"
#include "AnimGraphNode_Root.h"
#include "AnimGraphNode_SaveCachedPose.h"
#include "AnimGraphNode_SequencePlayer.h"
#include "AnimGraphNode_Slot.h"
#include "AnimGraphNode_StateMachineBase.h"
#include "AnimGraphNode_StateResult.h"
#include "AnimGraphNode_TransitionResult.h"
#include "AnimGraphNode_UseCachedPose.h"
#include "AnimStateAliasNode.h"
#include "AnimStateConduitNode.h"
#include "AnimStateEntryNode.h"
#include "AnimStateNode.h"
#include "AnimStateNodeBase.h"
#include "AnimStateTransitionNode.h"
#include "Dom/JsonObject.h"
#include "Curves/CurveBase.h"
#include "Curves/RichCurve.h"
#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "EdGraph/EdGraphPin.h"
#include "EdGraph/EdGraphSchema.h"
#include "EdGraphNode_Comment.h"
#include "Engine/Blueprint.h"
#include "Engine/SCS_Node.h"
#include "Engine/SimpleConstructionScript.h"
#include "K2Node.h"
#include "K2Node_CallFunction.h"
#include "K2Node_CustomEvent.h"
#include "K2Node_DynamicCast.h"
#include "K2Node_Event.h"
#include "K2Node_ExecutionSequence.h"
#include "K2Node_FunctionEntry.h"
#include "K2Node_FunctionResult.h"
#include "K2Node_IfThenElse.h"
#include "K2Node_Knot.h"
#include "K2Node_MacroInstance.h"
#include "K2Node_BreakStruct.h"
#include "K2Node_BaseMCDelegate.h"
#include "K2Node_CreateDelegate.h"
#include "K2Node_MakeStruct.h"
#include "K2Node_SetFieldsInStruct.h"
#include "K2Node_StructOperation.h"
#include "K2Node_Select.h"
#include "K2Node_Self.h"
#include "K2Node_SpawnActorFromClass.h"
#include "K2Node_Switch.h"
#include "K2Node_Tunnel.h"
#include "K2Node_Variable.h"
#include "K2Node_VariableGet.h"
#include "K2Node_VariableSet.h"
#include "HAL/FileManager.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "UObject/FindObjectFlags.h"
#include "UObject/UnrealType.h"
#include "UObject/UObjectGlobals.h"

namespace UnrealAssetTool
{
    static constexpr int32 SchemaVersion = 13;
    static constexpr int32 SourceChunkLines = 200;

    class FJsonlWriter
    {
    public:
        explicit FJsonlWriter(const FString& Filename)
        {
            Archive.Reset(IFileManager::Get().CreateFileWriter(*Filename));
        }

        bool IsValid() const
        {
            return Archive.IsValid();
        }

        bool Write(const TSharedRef<FJsonObject>& Object)
        {
            if (!Archive)
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
            Archive->Serialize(const_cast<ANSICHAR*>(Utf8.Get()), Utf8.Length());
            return !Archive->IsError();
        }

    private:
        TUniquePtr<FArchive> Archive;
    };

    struct FScanCounts
    {
        int64 Files = 0;
        int64 SourceChunks = 0;
        int64 Assets = 0;
        int64 AssetDependencies = 0;
        int64 Blueprints = 0;
        int64 BlueprintGraphs = 0;
        int64 BlueprintNodes = 0;
        int64 BlueprintPins = 0;
        int64 BlueprintSemanticNodes = 0;
        int64 BlueprintNodeProperties = 0;
        int64 BlueprintNodeReferences = 0;
        int64 BlueprintBindings = 0;
        int64 BlueprintInterfaces = 0;
        int64 RigVMObjects = 0;
        int64 RigVMPins = 0;
        int64 RigVMLinks = 0;
        int64 RigVMProperties = 0;
        int64 RigVMReferences = 0;
        int64 BlueprintEdges = 0;
        int64 BlueprintVariables = 0;
        int64 BlueprintComponents = 0;
        int64 BlueprintDefaults = 0;
        int64 BlueprintComponentProperties = 0;
        int64 BlueprintStateValues = 0;
        int64 BlueprintTimelines = 0;
        int64 BlueprintTimelineTracks = 0;
        int64 BlueprintTimelineKeys = 0;
        int64 BlueprintWidgets = 0;
        int64 BlueprintWidgetProperties = 0;
        int64 BlueprintWidgetBindings = 0;
        int64 BlueprintWidgetAnimations = 0;
        int64 BlueprintWidgetAnimationBindings = 0;
        int64 BehaviorTrees = 0;
        int64 BehaviorTreeNodes = 0;
        int64 BehaviorTreeEdges = 0;
        int64 Blackboards = 0;
        int64 BlackboardKeys = 0;
        int64 EQSQueries = 0;
        int64 EQSOptions = 0;
        int64 EQSGenerators = 0;
        int64 EQSTests = 0;
        int64 StateTrees = 0;
        int64 StateTreeStates = 0;
        int64 StateTreeNodes = 0;
        int64 StateTreeTransitions = 0;
        int64 StateTreeBindings = 0;
        int64 AIProperties = 0;
        int64 PCGGraphs = 0;
        int64 PCGNodes = 0;
        int64 PCGPins = 0;
        int64 PCGEdges = 0;
        int64 PCGProperties = 0;
        int64 Materials = 0;
        int64 MaterialExpressions = 0;
        int64 MaterialEdges = 0;
        int64 MaterialProperties = 0;
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

    static bool IsGeneratedPath(const FString& RelativePath)
    {
        FString P = RelativePath;
        FPaths::NormalizeFilename(P);
        P = TEXT("/") + P.ToLower() + TEXT("/");

        static const TCHAR* Excluded[] =
        {
            TEXT("/.git/"),
            TEXT("/.vs/"),
            TEXT("/.idea/"),
            TEXT("/.uatool/"),
            TEXT("/binaries/"),
            TEXT("/deriveddatacache/"),
            TEXT("/intermediate/"),
            TEXT("/saved/")
        };

        for (const TCHAR* Segment : Excluded)
        {
            if (P.Contains(Segment, ESearchCase::IgnoreCase))
            {
                return true;
            }
        }
        return false;
    }

    static bool IsToolGeneratedPhysicalFile(const FString& RelativePath)
    {
        FString P = RelativePath;
        FPaths::NormalizeFilename(P);
        return P.EndsWith(TEXT(".uatool.zip"), ESearchCase::IgnoreCase);
    }

    static FString FileKind(const FString& RelativePath)
    {
        const FString Lower = RelativePath.ToLower();
        const FString Ext = FPaths::GetExtension(RelativePath, true).ToLower();

        if (Ext == TEXT(".uasset")) return TEXT("unreal_asset");
        if (Ext == TEXT(".umap")) return TEXT("unreal_map");
        if (Lower.EndsWith(TEXT(".build.cs"))) return TEXT("unreal_build_rules");
        if (Lower.EndsWith(TEXT(".target.cs"))) return TEXT("unreal_target_rules");
        if (Ext == TEXT(".uproject")) return TEXT("unreal_project");
        if (Ext == TEXT(".uplugin")) return TEXT("unreal_plugin");
        if (Ext == TEXT(".ini")) return TEXT("config");
        if (Ext == TEXT(".cpp") || Ext == TEXT(".cc") || Ext == TEXT(".cxx") || Ext == TEXT(".c")) return TEXT("source");
        if (Ext == TEXT(".h") || Ext == TEXT(".hpp") || Ext == TEXT(".inl")) return TEXT("header");
        if (Ext == TEXT(".usf") || Ext == TEXT(".ush")) return TEXT("shader_source");
        if (Ext == TEXT(".py")) return TEXT("python");
        if (Ext == TEXT(".cs")) return TEXT("csharp");
        if (Ext == TEXT(".json")) return TEXT("json");
        if (Ext == TEXT(".xml")) return TEXT("xml");
        if (Ext == TEXT(".md") || Ext == TEXT(".txt")) return TEXT("documentation");
        return TEXT("file");
    }

    static bool IsTextFile(const FString& RelativePath)
    {
        const FString Kind = FileKind(RelativePath);
        return Kind == TEXT("source") ||
               Kind == TEXT("header") ||
               Kind == TEXT("shader_source") ||
               Kind == TEXT("python") ||
               Kind == TEXT("csharp") ||
               Kind == TEXT("json") ||
               Kind == TEXT("xml") ||
               Kind == TEXT("documentation") ||
               Kind == TEXT("config") ||
               Kind == TEXT("unreal_project") ||
               Kind == TEXT("unreal_plugin") ||
               Kind == TEXT("unreal_build_rules") ||
               Kind == TEXT("unreal_target_rules");
    }

    static TSharedRef<FJsonObject> PinTypeToJson(const FEdGraphPinType& PinType)
    {
        const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
        Json->SetStringField(TEXT("category"), PinType.PinCategory.ToString());
        Json->SetStringField(TEXT("subcategory"), PinType.PinSubCategory.ToString());
        Json->SetNumberField(TEXT("container_type"), static_cast<int32>(PinType.ContainerType));
        Json->SetBoolField(TEXT("is_reference"), PinType.bIsReference);
        Json->SetBoolField(TEXT("is_const"), PinType.bIsConst);

        if (UObject* SubCategoryObject = PinType.PinSubCategoryObject.Get())
        {
            Json->SetStringField(TEXT("subcategory_object"), SubCategoryObject->GetPathName());
        }
        else
        {
            Json->SetStringField(TEXT("subcategory_object"), TEXT(""));
        }
        return Json;
    }

    static FString GraphKind(const UBlueprint* Blueprint, const UEdGraph* Graph)
    {
        // Prefer concrete animation graph classes over the generic Blueprint
        // graph arrays. This tells retrieval whether a graph is an AnimGraph,
        // state machine, state body, transition rule, or conduit rule.
        if (Graph->IsA<UAnimationStateMachineGraph>()) return TEXT("anim_state_machine");
        if (Graph->IsA<UAnimationStateGraph>()) return TEXT("anim_state");
        if (Graph->IsA<UAnimationTransitionGraph>()) return TEXT("anim_transition");
        if (Graph->GetSchema() && Graph->GetSchema()->IsA<UAnimationConduitGraphSchema>()) return TEXT("anim_conduit");
        if (Graph->IsA<UAnimationGraph>()) return TEXT("anim_graph");

        if (Blueprint->UbergraphPages.Contains(Graph)) return TEXT("ubergraph");
        if (Blueprint->FunctionGraphs.Contains(Graph)) return TEXT("function");
        if (Blueprint->MacroGraphs.Contains(Graph)) return TEXT("macro");
        if (Blueprint->DelegateSignatureGraphs.Contains(Graph)) return TEXT("delegate_signature");
        if (Blueprint->EventGraphs.Contains(Graph)) return TEXT("event_graph_generated");
        if (Blueprint->IntermediateGeneratedGraphs.Contains(Graph)) return TEXT("intermediate_generated");
        return TEXT("graph");
    }

    static FString GraphSystem(const UEdGraph* Graph)
    {
        if (!Graph)
        {
            return TEXT("");
        }

        const FString GraphClass = Graph->GetClass()->GetPathName();
        const FString SchemaClass = Graph->GetSchema() ? Graph->GetSchema()->GetClass()->GetPathName() : TEXT("");

        if (GraphClass.Contains(TEXT("ControlRig")) || SchemaClass.Contains(TEXT("ControlRig"))) return TEXT("control_rig");
        if (GraphClass.Contains(TEXT("BlendStack")) || SchemaClass.Contains(TEXT("BlendStack"))) return TEXT("blend_stack");
        if (GraphClass.Contains(TEXT("AnimGraph")) || GraphClass.Contains(TEXT("Animation")) ||
            SchemaClass.Contains(TEXT("AnimGraph")) || SchemaClass.Contains(TEXT("Animation"))) return TEXT("animation");
        if (SchemaClass.Contains(TEXT("WidgetGraphSchema"))) return TEXT("umg");
        if (SchemaClass.Contains(TEXT("EdGraphSchema_K2"))) return TEXT("k2");
        return TEXT("graph");
    }

    static FString MakeGraphId(const FString& BlueprintPath, const UEdGraph* Graph)
    {
        const FString GraphPath = Graph ? Graph->GetPathName() : TEXT("<null>");
        return FString::Printf(TEXT("%s::graph::%s"), *BlueprintPath, *GraphPath);
    }

    static FString MakeNodeId(const FString& BlueprintPath, const UEdGraph* Graph, const UEdGraphNode* Node, int32 FallbackIndex)
    {
        FString Guid = Node->NodeGuid.ToString(EGuidFormats::DigitsWithHyphensLower);
        if (!Node->NodeGuid.IsValid())
        {
            Guid = FString::Printf(TEXT("index-%d"), FallbackIndex);
        }
        return FString::Printf(TEXT("%s::node::%s"), *MakeGraphId(BlueprintPath, Graph), *Guid);
    }

    static FString MakePinId(const FString& NodeId, const UEdGraphPin* Pin, int32 FallbackIndex)
    {
        FString Guid = Pin->PinId.ToString(EGuidFormats::DigitsWithHyphensLower);
        if (!Pin->PinId.IsValid())
        {
            Guid = FString::Printf(TEXT("pin-%d"), FallbackIndex);
        }
        return FString::Printf(TEXT("%s::%s"), *NodeId, *Guid);
    }

    static bool SaveJsonObject(const FString& Filename, const TSharedRef<FJsonObject>& Object)
    {
        FString JsonText;
        const TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer =
            TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&JsonText);
        if (!FJsonSerializer::Serialize(Object, Writer))
        {
            return false;
        }
        return FFileHelper::SaveStringToFile(JsonText, *Filename, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
    }

    static void AddMemberReferenceFields(
        FMemberReference& Reference,
        UClass* SelfScope,
        const TSharedRef<FJsonObject>& Semantic,
        FString& OutSymbol,
        FString& OutOwner)
    {
        OutSymbol = Reference.GetMemberName().ToString();
        Semantic->SetStringField(TEXT("member_name"), OutSymbol);
        Semantic->SetStringField(TEXT("member_guid"), Reference.GetMemberGuid().ToString(EGuidFormats::DigitsWithHyphensLower));
        Semantic->SetStringField(TEXT("member_scope"), Reference.GetMemberScopeName());
        Semantic->SetBoolField(TEXT("self_context"), Reference.IsSelfContext());
        Semantic->SetBoolField(TEXT("local_scope"), Reference.IsLocalScope());

        UClass* ParentClass = Reference.GetMemberParentClass(SelfScope);
        if (!ParentClass)
        {
            ParentClass = Reference.GetScope(SelfScope);
        }
        OutOwner = ParentClass ? ParentClass->GetPathName() : TEXT("");
        Semantic->SetStringField(TEXT("member_parent_class"), OutOwner);
    }

    static FString GetPinDefaultObjectPath(const UEdGraphNode* Node, const FName PinName)
    {
        if (!Node)
        {
            return TEXT("");
        }

        for (const UEdGraphPin* Pin : Node->Pins)
        {
            if (Pin && Pin->PinName == PinName && Pin->DefaultObject)
            {
                return Pin->DefaultObject->GetPathName();
            }
        }
        return TEXT("");
    }

    static FString GetPinDefaultValue(const UEdGraphNode* Node, const FName PinName)
    {
        if (!Node)
        {
            return TEXT("");
        }

        for (const UEdGraphPin* Pin : Node->Pins)
        {
            if (Pin && Pin->PinName == PinName)
            {
                return Pin->DefaultValue;
            }
        }
        return TEXT("");
    }

    static bool ClassIsOrDerivedFromName(const UClass* Class, const FName BaseClassName);

    static FString ExportReflectedPropertyText(UObject* Object, const FName PropertyName)
    {
        if (!Object)
        {
            return TEXT("");
        }

        FProperty* Property = Object->GetClass()->FindPropertyByName(PropertyName);
        if (!Property)
        {
            return TEXT("");
        }

        const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
        if (!ValuePtr)
        {
            return TEXT("");
        }

        FString Value;
        Property->ExportTextItem_Direct(Value, ValuePtr, nullptr, Object, PPF_None, nullptr);
        return Value;
    }

    static FString ExportReflectedStructFieldText(
        UObject* Object,
        const FName StructPropertyName,
        const FName FieldName)
    {
        if (!Object)
        {
            return TEXT("");
        }

        FStructProperty* StructProperty = CastField<FStructProperty>(
            Object->GetClass()->FindPropertyByName(StructPropertyName));
        if (!StructProperty || !StructProperty->Struct)
        {
            return TEXT("");
        }

        FProperty* Field = StructProperty->Struct->FindPropertyByName(FieldName);
        if (!Field)
        {
            return TEXT("");
        }

        const void* StructValue = StructProperty->ContainerPtrToValuePtr<void>(Object);
        const void* FieldValue = Field->ContainerPtrToValuePtr<void>(StructValue);
        FString Value;
        Field->ExportTextItem_Direct(Value, FieldValue, nullptr, Object, PPF_None, nullptr);
        return Value;
    }

    static UObject* GetReflectedObjectProperty(UObject* Object, const FName PropertyName)
    {
        if (!Object)
        {
            return nullptr;
        }

        FObjectPropertyBase* Property = CastField<FObjectPropertyBase>(
            Object->GetClass()->FindPropertyByName(PropertyName));
        return Property ? Property->GetObjectPropertyValue_InContainer(Object) : nullptr;
    }

    static UObject* GetReflectedStructObjectProperty(
        UObject* Object,
        const FName StructPropertyName,
        const FName ChildPropertyName)
    {
        if (!Object)
        {
            return nullptr;
        }

        FStructProperty* StructProperty = CastField<FStructProperty>(
            Object->GetClass()->FindPropertyByName(StructPropertyName));
        if (!StructProperty || !StructProperty->Struct)
        {
            return nullptr;
        }

        FObjectPropertyBase* ChildProperty = CastField<FObjectPropertyBase>(
            StructProperty->Struct->FindPropertyByName(ChildPropertyName));
        if (!ChildProperty)
        {
            return nullptr;
        }

        const void* StructValue = StructProperty->ContainerPtrToValuePtr<void>(Object);
        const void* ChildValue = ChildProperty->ContainerPtrToValuePtr<void>(StructValue);
        return ChildProperty->GetObjectPropertyValue(ChildValue);
    }

    static UObject* GetReflectedNestedObjectProperty(
        UObject* Object,
        const TArray<FName>& PropertyPath)
    {
        if (!Object || PropertyPath.IsEmpty())
        {
            return nullptr;
        }

        const UStruct* CurrentStruct = Object->GetClass();
        const void* CurrentContainer = Object;

        for (int32 Index = 0; Index < PropertyPath.Num(); ++Index)
        {
            if (!CurrentStruct || !CurrentContainer)
            {
                return nullptr;
            }

            FProperty* Property = CurrentStruct->FindPropertyByName(PropertyPath[Index]);
            if (!Property)
            {
                return nullptr;
            }

            const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(CurrentContainer);
            const bool bLast = Index == PropertyPath.Num() - 1;
            if (bLast)
            {
                if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
                {
                    return ObjectProperty->GetObjectPropertyValue(ValuePtr);
                }
                return nullptr;
            }

            const FStructProperty* StructProperty = CastField<FStructProperty>(Property);
            if (!StructProperty || !StructProperty->Struct)
            {
                return nullptr;
            }

            CurrentStruct = StructProperty->Struct;
            CurrentContainer = ValuePtr;
        }

        return nullptr;
    }

    static TArray<FString> GetReflectedStructArrayFieldTexts(
        UObject* Object,
        const FName StructPropertyName,
        const FName ArrayPropertyName,
        const FName ElementFieldName)
    {
        TArray<FString> Result;
        if (!Object)
        {
            return Result;
        }

        FStructProperty* StructProperty = CastField<FStructProperty>(
            Object->GetClass()->FindPropertyByName(StructPropertyName));
        if (!StructProperty || !StructProperty->Struct)
        {
            return Result;
        }

        FArrayProperty* ArrayProperty = CastField<FArrayProperty>(
            StructProperty->Struct->FindPropertyByName(ArrayPropertyName));
        FStructProperty* InnerStructProperty = ArrayProperty
            ? CastField<FStructProperty>(ArrayProperty->Inner)
            : nullptr;
        if (!ArrayProperty || !InnerStructProperty || !InnerStructProperty->Struct)
        {
            return Result;
        }

        FProperty* ElementField = InnerStructProperty->Struct->FindPropertyByName(ElementFieldName);
        if (!ElementField)
        {
            return Result;
        }

        const void* StructValue = StructProperty->ContainerPtrToValuePtr<void>(Object);
        const void* ArrayValue = ArrayProperty->ContainerPtrToValuePtr<void>(StructValue);
        FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
        Result.Reserve(Helper.Num());

        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            const void* ElementValue = Helper.GetRawPtr(Index);
            const void* FieldValue = ElementField->ContainerPtrToValuePtr<void>(ElementValue);
            FString FieldText;
            ElementField->ExportTextItem_Direct(
                FieldText,
                FieldValue,
                nullptr,
                Object,
                PPF_None,
                nullptr);
            Result.Add(MoveTemp(FieldText));
        }
        return Result;
    }

    static TArray<FString> GetReflectedArrayElementTexts(UObject* Object, const FName PropertyName)
    {
        TArray<FString> Result;
        if (!Object)
        {
            return Result;
        }

        FArrayProperty* ArrayProperty = CastField<FArrayProperty>(
            Object->GetClass()->FindPropertyByName(PropertyName));
        if (!ArrayProperty || !ArrayProperty->Inner)
        {
            return Result;
        }

        const void* ArrayValue = ArrayProperty->ContainerPtrToValuePtr<void>(Object);
        FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
        Result.Reserve(Helper.Num());

        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            FString ElementText;
            ArrayProperty->Inner->ExportTextItem_Direct(
                ElementText,
                Helper.GetRawPtr(Index),
                nullptr,
                Object,
                PPF_None,
                nullptr);
            Result.Add(MoveTemp(ElementText));
        }
        return Result;
    }

    static void ApplyReflectedSemanticEnrichment(
        UBlueprint* Blueprint,
        UEdGraphNode* Node,
        const TSharedRef<FJsonObject>& Semantic,
        FString& OutOperation,
        FString& OutSymbol,
        FString& OutOwner)
    {
        if (!Node)
        {
            return;
        }

        const auto SetAssetReference = [&OutSymbol, &OutOwner, &Semantic](
            const TCHAR* FieldName,
            UObject* Asset)
        {
            if (!Asset)
            {
                return;
            }
            const FString AssetPath = Asset->GetPathName();
            OutSymbol = Asset->GetName();
            OutOwner = AssetPath;
            Semantic->SetStringField(FieldName, AssetPath);
            Semantic->SetStringField(
                FString::Printf(TEXT("%s_class"), FieldName),
                Asset->GetClass()->GetPathName());
        };

        if (OutOperation == TEXT("property_access"))
        {
            const FString TextPath = ExportReflectedPropertyText(Node, TEXT("TextPath"));
            if (!TextPath.IsEmpty())
            {
                OutSymbol = TextPath;
                Semantic->SetStringField(TEXT("access_path"), TextPath);
            }

            const TArray<FString> Segments = GetReflectedArrayElementTexts(Node, TEXT("Path"));
            TArray<TSharedPtr<FJsonValue>> SegmentJson;
            SegmentJson.Reserve(Segments.Num());
            for (const FString& Segment : Segments)
            {
                SegmentJson.Add(MakeShared<FJsonValueString>(Segment));
            }
            Semantic->SetArrayField(TEXT("path_segments"), SegmentJson);
        }
        else if (OutOperation == TEXT("evaluate_chooser"))
        {
            SetAssetReference(TEXT("chooser_asset"), GetReflectedObjectProperty(Node, TEXT("Chooser")));
        }
        else if (OutOperation == TEXT("evaluate_proxy"))
        {
            SetAssetReference(TEXT("proxy_asset"), GetReflectedObjectProperty(Node, TEXT("Proxy")));
        }
        else if (OutOperation == TEXT("anim_blend_space_player"))
        {
            SetAssetReference(
                TEXT("blend_space"),
                GetReflectedStructObjectProperty(Node, TEXT("Node"), TEXT("BlendSpace")));
        }
        else if (OutOperation == TEXT("anim_sequence_evaluator"))
        {
            SetAssetReference(
                TEXT("animation_asset"),
                GetReflectedStructObjectProperty(Node, TEXT("Node"), TEXT("Sequence")));
        }
        else if (OutOperation == TEXT("anim_pose_driver"))
        {
            SetAssetReference(
                TEXT("pose_asset"),
                GetReflectedStructObjectProperty(Node, TEXT("Node"), TEXT("PoseAsset")));

            const TArray<FString> SourceBones = GetReflectedStructArrayFieldTexts(
                Node, TEXT("Node"), TEXT("SourceBones"), TEXT("BoneName"));
            TArray<TSharedPtr<FJsonValue>> SourceBoneJson;
            SourceBoneJson.Reserve(SourceBones.Num());
            for (const FString& BoneName : SourceBones)
            {
                SourceBoneJson.Add(MakeShared<FJsonValueString>(BoneName));
            }
            Semantic->SetArrayField(TEXT("source_bones"), SourceBoneJson);
            if (OutSymbol.IsEmpty() && SourceBones.Num() == 1)
            {
                OutSymbol = SourceBones[0];
            }
        }
        else if (OutOperation == TEXT("anim_control_rig"))
        {
            UObject* RigClass = GetReflectedNestedObjectProperty(
                Node,
                TArray<FName>{ FName(TEXT("Node")), FName(TEXT("ControlRigAssetReference")), FName(TEXT("BlueprintRigClass")) });
            if (!RigClass)
            {
                RigClass = GetReflectedNestedObjectProperty(
                    Node,
                    TArray<FName>{ FName(TEXT("Node")), FName(TEXT("DefaultControlRigAssetReference")), FName(TEXT("BlueprintRigClass")) });
            }
            SetAssetReference(TEXT("control_rig_class"), RigClass);
        }
        else if (OutOperation == TEXT("anim_motion_matching"))
        {
            if (UObject* BlendProfile = GetReflectedStructObjectProperty(Node, TEXT("Node"), TEXT("BlendProfile")))
            {
                Semantic->SetStringField(TEXT("blend_profile"), BlendProfile->GetPathName());
            }
        }
        else if (OutOperation == TEXT("async_action") ||
                 OutOperation == TEXT("ai_move_to") ||
                 OutOperation.StartsWith(TEXT("in_app_purchase_")))
        {
            const FString FactoryFunction = ExportReflectedPropertyText(Node, TEXT("ProxyFactoryFunctionName"));
            const FString ActivateFunction = ExportReflectedPropertyText(Node, TEXT("ProxyActivateFunctionName"));
            if (!FactoryFunction.IsEmpty() && FactoryFunction != TEXT("None"))
            {
                OutSymbol = FactoryFunction;
                Semantic->SetStringField(TEXT("factory_function"), FactoryFunction);
            }
            if (!ActivateFunction.IsEmpty() && ActivateFunction != TEXT("None"))
            {
                Semantic->SetStringField(TEXT("activate_function"), ActivateFunction);
            }
            if (UObject* FactoryClass = GetReflectedObjectProperty(Node, TEXT("ProxyFactoryClass")))
            {
                OutOwner = FactoryClass->GetPathName();
                Semantic->SetStringField(TEXT("factory_class"), OutOwner);
            }
            if (UObject* ProxyClass = GetReflectedObjectProperty(Node, TEXT("ProxyClass")))
            {
                Semantic->SetStringField(TEXT("proxy_class"), ProxyClass->GetPathName());
            }
        }
        else if (OutOperation == TEXT("legacy_input_action"))
        {
            OutSymbol = ExportReflectedPropertyText(Node, TEXT("InputActionName"));
            Semantic->SetStringField(TEXT("input_action_name"), OutSymbol);
            Semantic->SetStringField(TEXT("consume_input"), ExportReflectedPropertyText(Node, TEXT("bConsumeInput")));
            Semantic->SetStringField(TEXT("execute_when_paused"), ExportReflectedPropertyText(Node, TEXT("bExecuteWhenPaused")));
            Semantic->SetStringField(TEXT("override_parent_binding"), ExportReflectedPropertyText(Node, TEXT("bOverrideParentBinding")));
        }
        else if (OutOperation == TEXT("data_table_row"))
        {
            const FString DataTablePath = GetPinDefaultObjectPath(Node, TEXT("DataTable"));
            const FString RowName = GetPinDefaultValue(Node, TEXT("RowName"));
            if (!DataTablePath.IsEmpty())
            {
                OutOwner = DataTablePath;
                Semantic->SetStringField(TEXT("data_table"), DataTablePath);
            }
            if (!RowName.IsEmpty())
            {
                OutSymbol = RowName;
                Semantic->SetStringField(TEXT("row_name"), RowName);
            }
        }
        else if (OutOperation == TEXT("delegate_clear") ||
                 OutOperation == TEXT("delegate_bind") ||
                 OutOperation == TEXT("delegate_unbind") ||
                 OutOperation == TEXT("delegate_call") ||
                 OutOperation == TEXT("delegate_assign"))
        {
            if (UK2Node_BaseMCDelegate* DelegateNode = Cast<UK2Node_BaseMCDelegate>(Node))
            {
                UClass* SelfScope = Blueprint
                    ? (Blueprint->SkeletonGeneratedClass
                        ? Blueprint->SkeletonGeneratedClass
                        : Blueprint->GeneratedClass)
                    : nullptr;
                AddMemberReferenceFields(
                    DelegateNode->DelegateReference,
                    SelfScope,
                    Semantic,
                    OutSymbol,
                    OutOwner);

                Semantic->SetStringField(TEXT("delegate_name"), OutSymbol);
                Semantic->SetStringField(TEXT("delegate_owner"), OutOwner);
                Semantic->SetStringField(
                    TEXT("delegate_member_guid"),
                    DelegateNode->DelegateReference.GetMemberGuid().ToString(
                        EGuidFormats::DigitsWithHyphensLower));
                Semantic->SetStringField(
                    TEXT("delegate_member_scope"),
                    DelegateNode->DelegateReference.GetMemberScopeName());
                Semantic->SetBoolField(
                    TEXT("delegate_self_context"),
                    DelegateNode->DelegateReference.IsSelfContext());
                Semantic->SetBoolField(
                    TEXT("delegate_local_scope"),
                    DelegateNode->DelegateReference.IsLocalScope());
            }
            else
            {
                // Retain reflected fallback for unexpected plugin-derived
                // delegate nodes that serialize the standard reference shape.
                OutSymbol = ExportReflectedStructFieldText(
                    Node, TEXT("DelegateReference"), TEXT("MemberName"));
                Semantic->SetStringField(TEXT("delegate_name"), OutSymbol);
                if (UObject* Parent = GetReflectedStructObjectProperty(
                        Node, TEXT("DelegateReference"), TEXT("MemberParent")))
                {
                    OutOwner = Parent->GetPathName();
                    Semantic->SetStringField(TEXT("delegate_owner"), OutOwner);
                }
            }
        }
        else if (OutOperation == TEXT("delegate_create"))
        {
            if (UK2Node_CreateDelegate* CreateDelegate = Cast<UK2Node_CreateDelegate>(Node))
            {
                OutSymbol = CreateDelegate->SelectedFunctionName.ToString();
                Semantic->SetStringField(TEXT("selected_function"), OutSymbol);
                Semantic->SetStringField(
                    TEXT("selected_function_guid"),
                    CreateDelegate->SelectedFunctionGuid.ToString(
                        EGuidFormats::DigitsWithHyphensLower));

                if (UClass* ScopeClass = CreateDelegate->GetScopeClass(false))
                {
                    Semantic->SetStringField(
                        TEXT("selected_function_scope_class"),
                        ScopeClass->GetPathName());
                    if (UFunction* SelectedFunction =
                            ScopeClass->FindFunctionByName(CreateDelegate->SelectedFunctionName))
                    {
                        Semantic->SetStringField(
                            TEXT("selected_function_path"),
                            SelectedFunction->GetPathName());
                        if (UObject* SelectedOwner = SelectedFunction->GetOuter())
                        {
                            Semantic->SetStringField(
                                TEXT("selected_function_owner"),
                                SelectedOwner->GetPathName());
                        }
                    }
                }
            }
            else
            {
                OutSymbol = ExportReflectedPropertyText(Node, TEXT("SelectedFunctionName"));
                Semantic->SetStringField(TEXT("selected_function"), OutSymbol);
                Semantic->SetStringField(
                    TEXT("selected_function_guid"),
                    ExportReflectedPropertyText(Node, TEXT("SelectedFunctionGuid")));
            }
        }
        else if (OutOperation == TEXT("timeline"))
        {
            OutSymbol = ExportReflectedPropertyText(Node, TEXT("TimelineName"));
            Semantic->SetStringField(TEXT("timeline_name"), OutSymbol);
        }
        else if (OutOperation == TEXT("input_key"))
        {
            OutSymbol = ExportReflectedStructFieldText(Node, TEXT("InputKey"), TEXT("KeyName"));
            Semantic->SetStringField(TEXT("key"), OutSymbol);
            Semantic->SetStringField(TEXT("consume_input"), ExportReflectedPropertyText(Node, TEXT("bConsumeInput")));
            Semantic->SetStringField(TEXT("execute_when_paused"), ExportReflectedPropertyText(Node, TEXT("bExecuteWhenPaused")));
        }
        else if (OutOperation == TEXT("get_subsystem") ||
                 OutOperation == TEXT("get_engine_subsystem") ||
                 OutOperation == TEXT("get_editor_subsystem") ||
                 OutOperation == TEXT("get_subsystem_from_player_controller"))
        {
            if (UObject* SubsystemClass = GetReflectedObjectProperty(Node, TEXT("CustomClass")))
            {
                OutSymbol = SubsystemClass->GetName();
                OutOwner = SubsystemClass->GetPathName();
                Semantic->SetStringField(TEXT("subsystem_class"), OutOwner);
            }
        }
        else if (OutOperation == TEXT("anim_node_reference"))
        {
            OutSymbol = ExportReflectedPropertyText(Node, TEXT("Tag"));
            if (!OutSymbol.IsEmpty() && OutSymbol != TEXT("None"))
            {
                Semantic->SetStringField(TEXT("tag"), OutSymbol);
            }
        }
        else if (OutOperation == TEXT("anim_ik_rig"))
        {
            SetAssetReference(
                TEXT("ik_rig"),
                GetReflectedStructObjectProperty(Node, TEXT("Node"), TEXT("RigDefinitionAsset")));
        }
        else if (OutOperation == TEXT("anim_mirror"))
        {
            SetAssetReference(
                TEXT("mirror_data_table"),
                GetReflectedStructObjectProperty(Node, TEXT("Node"), TEXT("MirrorDataTable")));
        }
        else if (OutOperation == TEXT("anim_rotation_offset_blend_space"))
        {
            SetAssetReference(
                TEXT("blend_space"),
                GetReflectedStructObjectProperty(Node, TEXT("Node"), TEXT("BlendSpace")));
        }
        else if (OutOperation == TEXT("anim_rigid_body_with_control"))
        {
            if (UObject* PhysicsAsset = GetReflectedStructObjectProperty(Node, TEXT("Node"), TEXT("OverridePhysicsAsset")))
            {
                Semantic->SetStringField(TEXT("physics_asset"), PhysicsAsset->GetPathName());
            }
            if (UObject* ControlAsset = GetReflectedStructObjectProperty(Node, TEXT("Node"), TEXT("PhysicsControlAsset")))
            {
                Semantic->SetStringField(TEXT("physics_control_asset"), ControlAsset->GetPathName());
            }
        }
        else if (OutOperation == TEXT("anim_blend_space_graph"))
        {
            SetAssetReference(TEXT("blend_space"), GetReflectedObjectProperty(Node, TEXT("BlendSpace")));
            if (UObject* BoundGraph = GetReflectedObjectProperty(Node, TEXT("BlendSpaceGraph")))
            {
                Semantic->SetStringField(TEXT("blend_space_graph"), BoundGraph->GetPathName());
            }
        }
        else if (OutOperation == TEXT("anim_linked_graph"))
        {
            if (UObject* InstanceClass = GetReflectedStructObjectProperty(Node, TEXT("Node"), TEXT("InstanceClass")))
            {
                OutOwner = InstanceClass->GetPathName();
                Semantic->SetStringField(TEXT("instance_class"), OutOwner);
            }
            OutSymbol = ExportReflectedStructFieldText(Node, TEXT("FunctionReference"), TEXT("MemberName"));
            Semantic->SetStringField(TEXT("function_name"), OutSymbol);
            const FString Tag = ExportReflectedPropertyText(Node, TEXT("Tag"));
            if (!Tag.IsEmpty() && Tag != TEXT("None"))
            {
                Semantic->SetStringField(TEXT("tag"), Tag);
            }
        }
        else if (OutOperation == TEXT("anim_chooser_player"))
        {
            const FString ChooserDefinition = ExportReflectedStructFieldText(Node, TEXT("Node"), TEXT("Chooser"));
            if (!ChooserDefinition.IsEmpty())
            {
                OutSymbol = ChooserDefinition;
                Semantic->SetStringField(TEXT("chooser_definition"), ChooserDefinition);
            }
            if (UObject* BoundGraph = GetReflectedObjectProperty(Node, TEXT("BoundGraph")))
            {
                Semantic->SetStringField(TEXT("bound_graph"), BoundGraph->GetPathName());
            }
        }
        else if (OutOperation == TEXT("anim_blend_space_sample_result"))
        {
            const FString LayerGroup = ExportReflectedStructFieldText(Node, TEXT("Node"), TEXT("LayerGroup"));
            if (!LayerGroup.IsEmpty() && LayerGroup != TEXT("None"))
            {
                OutSymbol = LayerGroup;
                Semantic->SetStringField(TEXT("layer_group"), LayerGroup);
            }
        }
        else if (OutOperation == TEXT("control_rig_node"))
        {
            OutSymbol = ExportReflectedPropertyText(Node, TEXT("ModelNodePath"));
            OutOwner = Node->GetGraph() ? Node->GetGraph()->GetPathName() :
                (Blueprint ? Blueprint->GetPathName() : TEXT(""));
            Semantic->SetStringField(TEXT("model_node_path"), OutSymbol);
            Semantic->SetStringField(TEXT("semantic_depth"), TEXT("model_node_reference"));
        }

        // AnimGraph editor nodes expose optional lifecycle callbacks through
        // FMemberReference fields on the node itself. Capture them generically
        // so plugin-specific animation nodes also become explainable without
        // hard-linking against every editor module.
        const auto AddAnimLifecycleFunction = [&Semantic, Node](const FName PropertyName, const TCHAR* JsonField)
        {
            const FString MemberName = ExportReflectedStructFieldText(Node, PropertyName, TEXT("MemberName"));
            if (MemberName.IsEmpty() || MemberName == TEXT("None"))
            {
                return;
            }

            const TSharedRef<FJsonObject> FunctionJson = MakeShared<FJsonObject>();
            FunctionJson->SetStringField(TEXT("name"), MemberName);
            if (UObject* Parent = GetReflectedStructObjectProperty(Node, PropertyName, TEXT("MemberParent")))
            {
                FunctionJson->SetStringField(TEXT("owner"), Parent->GetPathName());
            }
            Semantic->SetObjectField(JsonField, FunctionJson);
        };

        AddAnimLifecycleFunction(TEXT("InitialUpdateFunction"), TEXT("initial_update_function"));
        AddAnimLifecycleFunction(TEXT("BecomeRelevantFunction"), TEXT("become_relevant_function"));
        AddAnimLifecycleFunction(TEXT("UpdateFunction"), TEXT("update_function"));
    }

    static void ApplyClassSemanticFallback(
        UEdGraphNode* Node,
        const TSharedRef<FJsonObject>& Semantic,
        FString& OutOperation,
        FString& OutSymbol,
        FString& OutOwner)
    {
        if (!Node || OutOperation != TEXT("node"))
        {
            return;
        }

        struct FClassSemantic
        {
            const TCHAR* ClassName;
            const TCHAR* Operation;
        };

        static const FClassSemantic KnownClasses[] =
        {
            { TEXT("K2Node_PropertyAccess"), TEXT("property_access") },
            { TEXT("K2Node_EnumEquality"), TEXT("enum_equal") },
            { TEXT("K2Node_EnumInequality"), TEXT("enum_not_equal") },
            { TEXT("K2Node_MakeArray"), TEXT("make_array") },
            { TEXT("K2Node_GetArrayItem"), TEXT("array_get") },
            { TEXT("K2Node_AddDelegate"), TEXT("delegate_bind") },
            { TEXT("K2Node_RemoveDelegate"), TEXT("delegate_unbind") },
            { TEXT("K2Node_CreateDelegate"), TEXT("delegate_create") },
            { TEXT("K2Node_CallDelegate"), TEXT("delegate_call") },
            { TEXT("K2Node_GetEnumeratorNameAsString"), TEXT("enum_to_string") },
            { TEXT("K2Node_VariableSetRef"), TEXT("variable_set_ref") },
            { TEXT("K2Node_InputKey"), TEXT("input_key") },
            { TEXT("K2Node_EnhancedInputAction"), TEXT("enhanced_input_event") },
            { TEXT("K2Node_GetInputActionValue"), TEXT("enhanced_input_value") },
            { TEXT("K2Node_GetSubsystem"), TEXT("get_subsystem") },
            { TEXT("K2Node_GetEngineSubsystem"), TEXT("get_engine_subsystem") },
            { TEXT("K2Node_GetEditorSubsystem"), TEXT("get_editor_subsystem") },
            { TEXT("K2Node_GetSubsystemFromPC"), TEXT("get_subsystem_from_player_controller") },
            { TEXT("K2Node_FormatText"), TEXT("format_text") },
            { TEXT("K2Node_ConvertAsset"), TEXT("convert_asset") },
            { TEXT("K2Node_GetClassDefaults"), TEXT("get_class_defaults") },
            { TEXT("K2Node_Timeline"), TEXT("timeline") },
            { TEXT("K2Node_LoadAssetClass"), TEXT("load_asset_class") },
            { TEXT("K2Node_CreateWidget"), TEXT("create_widget") },
            { TEXT("K2Node_EvaluateChooser2"), TEXT("evaluate_chooser") },
            { TEXT("K2Node_GetChooserContextParameters"), TEXT("chooser_context_parameters") },
            { TEXT("K2Node_PlayMontageOnMoverActor"), TEXT("mover_play_montage") },
            { TEXT("K2Node_PlayMontage"), TEXT("anim_play_montage") },
            { TEXT("K2Node_AnimNodeReference"), TEXT("anim_node_reference") },
            { TEXT("K2Node_AsyncAction"), TEXT("async_action") },
            { TEXT("K2Node_InputAction"), TEXT("legacy_input_action") },
            { TEXT("K2Node_GetDataTableRow"), TEXT("data_table_row") },
            { TEXT("K2Node_ClearDelegate"), TEXT("delegate_clear") },
            { TEXT("K2Node_AIMoveTo"), TEXT("ai_move_to") },
            { TEXT("K2Node_InAppPurchaseQuery2"), TEXT("in_app_purchase_query") },
            { TEXT("K2Node_InAppPurchaseCheckout"), TEXT("in_app_purchase_checkout") },
            { TEXT("K2Node_InAppPurchaseFinalize"), TEXT("in_app_purchase_finalize") },

            { TEXT("AnimGraphNode_PoseDriver"), TEXT("anim_pose_driver") },
            { TEXT("AnimGraphNode_LocalToComponentSpace"), TEXT("anim_local_to_component_space") },
            { TEXT("AnimGraphNode_ComponentToLocalSpace"), TEXT("anim_component_to_local_space") },
            { TEXT("AnimGraphNode_ControlRig"), TEXT("anim_control_rig") },
            { TEXT("AnimGraphNode_ModifyCurve"), TEXT("anim_modify_curve") },
            { TEXT("AnimGraphNode_ModifyBone"), TEXT("anim_modify_bone") },
            { TEXT("AnimGraphNode_BlendSpacePlayer"), TEXT("anim_blend_space_player") },
            { TEXT("AnimGraphNode_SequenceEvaluator"), TEXT("anim_sequence_evaluator") },
            { TEXT("AnimGraphNode_BlendListByBool"), TEXT("anim_blend_by_bool") },
            { TEXT("AnimGraphNode_BlendListByEnum"), TEXT("anim_blend_by_enum") },
            { TEXT("AnimGraphNode_BlendListByInt"), TEXT("anim_blend_by_int") },
            { TEXT("AnimGraphNode_TwoWayBlend"), TEXT("anim_two_way_blend") },
            { TEXT("AnimGraphNode_ApplyMeshSpaceAdditive"), TEXT("anim_apply_mesh_space_additive") },
            { TEXT("AnimGraphNode_RigidBody"), TEXT("anim_rigid_body") },
            { TEXT("AnimGraphNode_CopyBone"), TEXT("anim_copy_bone") },
            { TEXT("AnimGraphNode_CopyPoseFromMesh"), TEXT("anim_copy_pose_from_mesh") },
            { TEXT("AnimGraphNode_TransitionPoseEvaluator"), TEXT("anim_transition_pose_evaluator") },
            { TEXT("AnimGraphNode_ResetRoot"), TEXT("anim_reset_root") },
            { TEXT("AnimGraphNode_DeadBlending"), TEXT("anim_dead_blending") },
            { TEXT("AnimGraphNode_Constraint"), TEXT("anim_constraint") },
            { TEXT("AnimGraphNode_LegIK"), TEXT("anim_leg_ik") },
            { TEXT("AnimGraphNode_Inertialization"), TEXT("anim_inertialization") },
            { TEXT("AnimGraphNode_IdentityPose"), TEXT("anim_identity_pose") },

            { TEXT("AnimGraphNode_Steering"), TEXT("anim_steering") },
            { TEXT("AnimGraphNode_OrientationWarping"), TEXT("anim_orientation_warping") },
            { TEXT("AnimGraphNode_OffsetRootBone"), TEXT("anim_offset_root_bone") },
            { TEXT("AnimGraphNode_BlendStackInput"), TEXT("anim_blend_stack_input") },
            { TEXT("AnimGraphNode_BlendStack"), TEXT("anim_blend_stack") },
            { TEXT("AnimGraphNode_RetargetPoseFromMesh"), TEXT("anim_retarget_pose_from_mesh") },
            { TEXT("AnimGraphNode_PoseSearchHistoryCollector"), TEXT("anim_pose_search_history") },
            { TEXT("AnimGraphNode_PoseSearchComponentSpaceHistoryCollector"), TEXT("anim_pose_search_component_history") },
            { TEXT("AnimGraphNode_MotionMatching"), TEXT("anim_motion_matching") },
            { TEXT("AnimGraphNode_LayeredBoneBlend"), TEXT("anim_layered_bone_blend") },
            { TEXT("AnimGraphNode_LocalRefPose"), TEXT("anim_local_ref_pose") },
            { TEXT("AnimGraphNode_PoseBlendNode"), TEXT("anim_pose_blend") },
            { TEXT("AnimGraphNode_PoseSnapshot"), TEXT("anim_pose_snapshot") },
            { TEXT("AnimGraphNode_FootPlacement"), TEXT("anim_foot_placement") },
            { TEXT("AnimGraphNode_StrideWarping"), TEXT("anim_stride_warping") },
            { TEXT("AnimGraphNode_RemapCurves"), TEXT("anim_remap_curves") },
            { TEXT("AnimGraphNode_LiveLinkPose"), TEXT("anim_live_link_pose") },
            { TEXT("AnimGraphNode_RigLogic"), TEXT("anim_rig_logic") },
            { TEXT("AnimGraphNode_IKRig"), TEXT("anim_ik_rig") },
            { TEXT("AnimGraphNode_BlendSpaceSampleResult"), TEXT("anim_blend_space_sample_result") },
            { TEXT("AnimGraphNode_Mirror"), TEXT("anim_mirror") },
            { TEXT("AnimGraphNode_ApplyAdditive"), TEXT("anim_apply_additive") },
            { TEXT("AnimGraphNode_RotationOffsetBlendSpace"), TEXT("anim_rotation_offset_blend_space") },
            { TEXT("AnimGraphNode_ChooserPlayer"), TEXT("anim_chooser_player") },
            { TEXT("AnimGraphNode_RigidBodyWithControl"), TEXT("anim_rigid_body_with_control") },
            { TEXT("AnimGraphNode_BlendSpaceGraph"), TEXT("anim_blend_space_graph") },
            { TEXT("AnimGraphNode_LinkedAnimGraph"), TEXT("anim_linked_graph") },
            { TEXT("AnimGraphNode_MultiWayBlend"), TEXT("anim_multi_way_blend") },

            { TEXT("K2Node_AddComponentByClass"), TEXT("add_component_by_class") },
            { TEXT("K2Node_AssignDelegate"), TEXT("delegate_assign") },
            { TEXT("K2Node_CastByteToEnum"), TEXT("cast_byte_to_enum") },
            { TEXT("K2Node_GenericCreateObject"), TEXT("create_object") },
            { TEXT("K2Node_LoadAsset"), TEXT("load_asset") },
            { TEXT("K2Node_MakeMap"), TEXT("make_map") },
            { TEXT("K2Node_MapForEach"), TEXT("map_for_each") },
            { TEXT("K2Node_LatentGameplayTaskCall"), TEXT("gameplay_task_call") },
            { TEXT("K2Node_InputDebugKey"), TEXT("input_debug_key") },
            { TEXT("K2Node_EvaluateLiveLinkFrameWithSpecificRole"), TEXT("evaluate_live_link_frame") },
            { TEXT("K2Node_EvaluateProxy2"), TEXT("evaluate_proxy") },
            { TEXT("ControlRigGraphNode"), TEXT("control_rig_node") }
        };

        const FString ClassName = Node->GetClass()->GetName();
        for (const FClassSemantic& Entry : KnownClasses)
        {
            if (ClassName == Entry.ClassName)
            {
                OutOperation = Entry.Operation;
                Semantic->SetStringField(TEXT("classification_source"), TEXT("node_class"));
                Semantic->SetStringField(TEXT("concrete_node_class"), Node->GetClass()->GetPathName());
                break;
            }
        }

        if (OutOperation == TEXT("enhanced_input_event") ||
            OutOperation == TEXT("enhanced_input_value"))
        {
            const FString InputActionPath = GetPinDefaultObjectPath(Node, TEXT("InputAction"));
            if (!InputActionPath.IsEmpty())
            {
                OutOwner = InputActionPath;
                OutSymbol = FPackageName::ObjectPathToObjectName(InputActionPath);
                Semantic->SetStringField(TEXT("input_action"), InputActionPath);
            }
        }
    }

    struct FNodePropertyScanContext
    {
        UEdGraphNode* Node = nullptr;
        FString NodeId;
        FString BlueprintPath;
        FString GraphName;
        FJsonlWriter* PropertiesWriter = nullptr;
        FJsonlWriter* ReferencesWriter = nullptr;
        FScanCounts* Counts = nullptr;
        TSet<const UObject*> VisitedObjects;
    };

    static bool IsCapturableProperty(const FProperty* Property)
    {
        return Property &&
            !Property->HasAnyPropertyFlags(
                CPF_Transient | CPF_DuplicateTransient | CPF_NonPIEDuplicateTransient);
    }

    static bool WriteNodePropertyRecord(
        FNodePropertyScanContext& Context,
        FProperty* Property,
        const void* ValuePtr,
        const FString& PropertyPath,
        const FString& DeclaringType,
        int32 Depth)
    {
        if (!Property || !ValuePtr || !Context.PropertiesWriter || !Context.ReferencesWriter || !Context.Counts)
        {
            return true;
        }

        static constexpr int32 MaxExportedPropertyChars = 65536;

        FString Value;
        Property->ExportTextItem_Direct(
            Value,
            ValuePtr,
            nullptr,
            Context.Node,
            PPF_None,
            nullptr);

        bool bTruncated = false;
        if (Value.Len() > MaxExportedPropertyChars)
        {
            Value = Value.Left(MaxExportedPropertyChars);
            bTruncated = true;
        }

        FString ObjectPath;
        FString ObjectClass;
        UObject* ObjectValue = nullptr;
        if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
        {
            ObjectValue = ObjectProperty->GetObjectPropertyValue(ValuePtr);
            if (ObjectValue)
            {
                ObjectPath = ObjectValue->GetPathName();
                ObjectClass = ObjectValue->GetClass()->GetPathName();
            }
        }

        const TSharedRef<FJsonObject> PropertyJson = MakeShared<FJsonObject>();
        PropertyJson->SetStringField(TEXT("node_id"), Context.NodeId);
        PropertyJson->SetStringField(TEXT("blueprint_path"), Context.BlueprintPath);
        PropertyJson->SetStringField(TEXT("graph_name"), Context.GraphName);
        PropertyJson->SetStringField(TEXT("node_class"), Context.Node->GetClass()->GetPathName());
        PropertyJson->SetStringField(TEXT("property_name"), Property->GetName());
        PropertyJson->SetStringField(TEXT("property_path"), PropertyPath);
        PropertyJson->SetStringField(TEXT("owner_class"), DeclaringType);
        PropertyJson->SetStringField(TEXT("declaring_type"), DeclaringType);
        PropertyJson->SetNumberField(TEXT("depth"), Depth);
        PropertyJson->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
        PropertyJson->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
        PropertyJson->SetStringField(TEXT("value"), Value);
        PropertyJson->SetStringField(TEXT("object_path"), ObjectPath);
        PropertyJson->SetStringField(TEXT("object_class"), ObjectClass);
        PropertyJson->SetNumberField(TEXT("property_flags"), static_cast<double>(Property->GetPropertyFlags()));
        PropertyJson->SetBoolField(TEXT("truncated"), bTruncated);

        if (!Context.PropertiesWriter->Write(PropertyJson))
        {
            return false;
        }
        ++Context.Counts->BlueprintNodeProperties;

        if (ObjectValue)
        {
            const TSharedRef<FJsonObject> ReferenceJson = MakeShared<FJsonObject>();
            ReferenceJson->SetStringField(TEXT("node_id"), Context.NodeId);
            ReferenceJson->SetStringField(TEXT("blueprint_path"), Context.BlueprintPath);
            ReferenceJson->SetStringField(TEXT("graph_name"), Context.GraphName);
            ReferenceJson->SetStringField(TEXT("node_class"), Context.Node->GetClass()->GetPathName());
            ReferenceJson->SetStringField(TEXT("property_path"), PropertyPath);
            ReferenceJson->SetStringField(TEXT("target_object_path"), ObjectPath);
            ReferenceJson->SetStringField(TEXT("target_class"), ObjectClass);
            ReferenceJson->SetBoolField(TEXT("node_owned"), ObjectValue->GetOuter() == Context.Node);

            if (!Context.ReferencesWriter->Write(ReferenceJson))
            {
                return false;
            }
            ++Context.Counts->BlueprintNodeReferences;
        }

        return true;
    }

    static bool ScanReflectedPropertyValue(
        FNodePropertyScanContext& Context,
        FProperty* Property,
        const void* ContainerPtr,
        const FString& PropertyPath,
        const FString& DeclaringType,
        int32 Depth);

    static bool ScanOwnedBindingObject(
        FNodePropertyScanContext& Context,
        UObject* ObjectValue,
        const FString& Prefix,
        int32 Depth)
    {
        if (!ObjectValue || Context.VisitedObjects.Contains(ObjectValue))
        {
            return true;
        }

        // Binding objects are editor-owned subobjects that contain the actual
        // property-access bindings for many AnimGraph pins. Do not recursively
        // walk arbitrary node-owned graphs/assets, which would explode the scan
        // and create cycles.
        if (!ObjectValue->GetClass()->GetName().Contains(TEXT("Binding")))
        {
            return true;
        }

        Context.VisitedObjects.Add(ObjectValue);

        for (UClass* Class = ObjectValue->GetClass();
             Class && Class != UObject::StaticClass();
             Class = Class->GetSuperClass())
        {
            for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
            {
                FProperty* Property = *It;
                if (!IsCapturableProperty(Property))
                {
                    continue;
                }

                const FString ChildPath = FString::Printf(
                    TEXT("%s.%s"),
                    *Prefix,
                    *Property->GetName());
                if (!ScanReflectedPropertyValue(
                        Context,
                        Property,
                        ObjectValue,
                        ChildPath,
                        Class->GetPathName(),
                        Depth))
                {
                    return false;
                }
            }
        }
        return true;
    }

    static bool ScanReflectedPropertyValue(
        FNodePropertyScanContext& Context,
        FProperty* Property,
        const void* ContainerPtr,
        const FString& PropertyPath,
        const FString& DeclaringType,
        int32 Depth)
    {
        if (!IsCapturableProperty(Property) || !ContainerPtr)
        {
            return true;
        }

        static constexpr int32 MaxNestedDepth = 4;
        static constexpr int32 MaxSimpleArrayElements = 64;

        const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(ContainerPtr);
        if (!ValuePtr)
        {
            return true;
        }

        if (!WriteNodePropertyRecord(
                Context,
                Property,
                ValuePtr,
                PropertyPath,
                DeclaringType,
                Depth))
        {
            return false;
        }

        if (Depth >= MaxNestedDepth)
        {
            return true;
        }

        if (FStructProperty* StructProperty = CastField<FStructProperty>(Property))
        {
            if (!StructProperty->Struct)
            {
                return true;
            }

            for (TFieldIterator<FProperty> It(StructProperty->Struct, EFieldIterationFlags::Default); It; ++It)
            {
                FProperty* ChildProperty = *It;
                if (!IsCapturableProperty(ChildProperty))
                {
                    continue;
                }

                const FString ChildPath = FString::Printf(
                    TEXT("%s.%s"),
                    *PropertyPath,
                    *ChildProperty->GetName());
                if (!ScanReflectedPropertyValue(
                        Context,
                        ChildProperty,
                        ValuePtr,
                        ChildPath,
                        StructProperty->Struct->GetPathName(),
                        Depth + 1))
                {
                    return false;
                }
            }
        }
        else if (FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
        {
            FProperty* Inner = ArrayProperty->Inner;
            if (!Inner ||
                CastField<FStructProperty>(Inner) ||
                CastField<FArrayProperty>(Inner) ||
                CastField<FSetProperty>(Inner) ||
                CastField<FMapProperty>(Inner))
            {
                return true;
            }

            FScriptArrayHelper Helper(ArrayProperty, ValuePtr);
            const int32 NumToWrite = FMath::Min(Helper.Num(), MaxSimpleArrayElements);
            for (int32 Index = 0; Index < NumToWrite; ++Index)
            {
                const void* ElementValue = Helper.GetRawPtr(Index);
                const FString ElementPath = FString::Printf(
                    TEXT("%s[%d]"),
                    *PropertyPath,
                    Index);
                if (!WriteNodePropertyRecord(
                        Context,
                        Inner,
                        ElementValue,
                        ElementPath,
                        DeclaringType,
                        Depth + 1))
                {
                    return false;
                }
            }
        }
        else if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
        {
            UObject* ObjectValue = ObjectProperty->GetObjectPropertyValue(ValuePtr);
            if (ObjectValue && ObjectValue->GetOuter() == Context.Node)
            {
                if (!ScanOwnedBindingObject(Context, ObjectValue, PropertyPath, Depth + 1))
                {
                    return false;
                }
            }
        }

        return true;
    }

    static bool ScanNodeProperties(
        UEdGraphNode* Node,
        const FString& NodeId,
        const FString& BlueprintPath,
        const FString& GraphName,
        FJsonlWriter& PropertiesWriter,
        FJsonlWriter& ReferencesWriter,
        FScanCounts& Counts)
    {
        if (!Node)
        {
            return true;
        }

        FNodePropertyScanContext Context;
        Context.Node = Node;
        Context.NodeId = NodeId;
        Context.BlueprintPath = BlueprintPath;
        Context.GraphName = GraphName;
        Context.PropertiesWriter = &PropertiesWriter;
        Context.ReferencesWriter = &ReferencesWriter;
        Context.Counts = &Counts;
        Context.VisitedObjects.Add(Node);

        for (UClass* Class = Node->GetClass();
             Class && Class != UEdGraphNode::StaticClass() && Class != UK2Node::StaticClass();
             Class = Class->GetSuperClass())
        {
            for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
            {
                FProperty* Property = *It;
                if (!IsCapturableProperty(Property))
                {
                    continue;
                }

                if (!ScanReflectedPropertyValue(
                        Context,
                        Property,
                        Node,
                        Property->GetName(),
                        Class->GetPathName(),
                        0))
                {
                    return false;
                }
            }
        }
        return true;
    }

    static TSharedRef<FJsonObject> BuildNodeSemantic(
        UBlueprint* Blueprint,
        UEdGraphNode* Node,
        FString& OutOperation,
        FString& OutSymbol,
        FString& OutOwner)
    {
        const TSharedRef<FJsonObject> Semantic = MakeShared<FJsonObject>();
        OutOperation = TEXT("node");
        OutSymbol.Reset();
        OutOwner.Reset();

        UClass* SelfScope = Blueprint
            ? (Blueprint->SkeletonGeneratedClass ? Blueprint->SkeletonGeneratedClass : Blueprint->GeneratedClass)
            : nullptr;

        const auto SetBoundGraph = [&Semantic](const TCHAR* FieldName, UEdGraph* BoundGraph)
        {
            Semantic->SetStringField(FieldName, BoundGraph ? BoundGraph->GetPathName() : TEXT(""));
        };

        // -----------------------------------------------------------------
        // Animation Blueprint semantics
        // -----------------------------------------------------------------
        if (UAnimGraphNode_StateMachineBase* StateMachine = Cast<UAnimGraphNode_StateMachineBase>(Node))
        {
            OutOperation = TEXT("anim_state_machine");
            OutSymbol = StateMachine->GetStateMachineName();
            OutOwner = Blueprint ? Blueprint->GetPathName() : TEXT("");
            Semantic->SetStringField(TEXT("state_machine_name"), OutSymbol);
            SetBoundGraph(TEXT("editor_state_machine_graph"), StateMachine->EditorStateMachineGraph.Get());
        }
        else if (UAnimStateEntryNode* Entry = Cast<UAnimStateEntryNode>(Node))
        {
            OutOperation = TEXT("anim_state_entry");
            if (UAnimStateNodeBase* TargetState = Cast<UAnimStateNodeBase>(Entry->GetOutputNode()))
            {
                OutSymbol = TargetState->GetStateName();
                Semantic->SetStringField(TEXT("target_state"), OutSymbol);
                Semantic->SetStringField(TEXT("target_node_guid"),
                    TargetState->NodeGuid.ToString(EGuidFormats::DigitsWithHyphensLower));
            }
        }
        else if (UAnimStateTransitionNode* Transition = Cast<UAnimStateTransitionNode>(Node))
        {
            OutOperation = TEXT("anim_transition");

            UAnimStateNodeBase* PreviousState = Transition->GetPreviousState();
            UAnimStateNodeBase* NextState = Transition->GetNextState();
            const FString PreviousName = PreviousState ? PreviousState->GetStateName() : TEXT("");
            const FString NextName = NextState ? NextState->GetStateName() : TEXT("");

            if (!PreviousName.IsEmpty() || !NextName.IsEmpty())
            {
                OutSymbol = FString::Printf(TEXT("%s -> %s"), *PreviousName, *NextName);
            }
            OutOwner = Transition->GetGraph() ? Transition->GetGraph()->GetPathName() : TEXT("");

            Semantic->SetStringField(TEXT("previous_state"), PreviousName);
            Semantic->SetStringField(TEXT("next_state"), NextName);
            Semantic->SetBoolField(TEXT("bidirectional"), Transition->Bidirectional);
            Semantic->SetBoolField(TEXT("disabled"), Transition->bDisabled);
            Semantic->SetBoolField(TEXT("automatic_rule"),
                Transition->bAutomaticRuleBasedOnSequencePlayerInState);
            Semantic->SetNumberField(TEXT("automatic_rule_trigger_time"),
                Transition->AutomaticRuleTriggerTime);
            Semantic->SetNumberField(TEXT("crossfade_duration"), Transition->CrossfadeDuration);
            Semantic->SetNumberField(TEXT("priority_order"), Transition->PriorityOrder);
            Semantic->SetNumberField(TEXT("logic_type"), static_cast<int32>(Transition->LogicType));
            Semantic->SetNumberField(TEXT("min_time_before_reentry"), Transition->MinTimeBeforeReentry);
            Semantic->SetBoolField(TEXT("only_evaluate_when_active"), Transition->bOnlyEvaluateWhenActive);
            Semantic->SetBoolField(TEXT("allow_inertialization_for_self_transitions"),
                Transition->bAllowInertializationForSelfTransitions);
            Semantic->SetBoolField(TEXT("shared_rules"), Transition->bSharedRules);
            Semantic->SetStringField(TEXT("shared_rules_name"), Transition->SharedRulesName);
            Semantic->SetBoolField(TEXT("shared_crossfade"), Transition->bSharedCrossfade);
            Semantic->SetStringField(TEXT("shared_crossfade_name"), Transition->SharedCrossfadeName);
            SetBoundGraph(TEXT("rule_graph"), Transition->BoundGraph.Get());
            SetBoundGraph(TEXT("custom_transition_graph"), Transition->CustomTransitionGraph.Get());
        }
        else if (UAnimStateNode* State = Cast<UAnimStateNode>(Node))
        {
            OutOperation = TEXT("anim_state");
            OutSymbol = State->GetStateName();
            OutOwner = State->GetGraph() ? State->GetGraph()->GetPathName() : TEXT("");
            Semantic->SetStringField(TEXT("state_name"), OutSymbol);
            Semantic->SetBoolField(TEXT("always_reset_on_entry"), State->bAlwaysResetOnEntry);
            Semantic->SetNumberField(TEXT("state_type"), static_cast<int32>(State->StateType));
            SetBoundGraph(TEXT("bound_graph"), State->GetBoundGraph());
        }
        else if (UAnimStateConduitNode* Conduit = Cast<UAnimStateConduitNode>(Node))
        {
            OutOperation = TEXT("anim_conduit");
            OutSymbol = Conduit->GetStateName();
            OutOwner = Conduit->GetGraph() ? Conduit->GetGraph()->GetPathName() : TEXT("");
            Semantic->SetStringField(TEXT("conduit_name"), OutSymbol);
            SetBoundGraph(TEXT("bound_graph"), Conduit->GetBoundGraph());
        }
        else if (UAnimStateAliasNode* Alias = Cast<UAnimStateAliasNode>(Node))
        {
            OutOperation = TEXT("anim_state_alias");
            OutSymbol = Alias->StateAliasName;
            OutOwner = Alias->GetGraph() ? Alias->GetGraph()->GetPathName() : TEXT("");
            Semantic->SetStringField(TEXT("alias_name"), OutSymbol);
            Semantic->SetBoolField(TEXT("global_alias"), Alias->bGlobalAlias);

            TArray<TSharedPtr<FJsonValue>> AliasedStates;
            for (const TWeakObjectPtr<UAnimStateNodeBase>& AliasedWeak : Alias->GetAliasedStates())
            {
                if (UAnimStateNodeBase* AliasedState = AliasedWeak.Get())
                {
                    AliasedStates.Add(MakeShared<FJsonValueString>(AliasedState->GetStateName()));
                }
            }
            Semantic->SetArrayField(TEXT("aliased_states"), AliasedStates);
        }
        else if (UAnimGraphNode_SaveCachedPose* SavePose = Cast<UAnimGraphNode_SaveCachedPose>(Node))
        {
            OutOperation = TEXT("anim_save_cached_pose");
            OutSymbol = SavePose->CacheName;
            OutOwner = Blueprint ? Blueprint->GetPathName() : TEXT("");
            Semantic->SetStringField(TEXT("cache_name"), OutSymbol);
        }
        else if (UAnimGraphNode_UseCachedPose* UsePose = Cast<UAnimGraphNode_UseCachedPose>(Node))
        {
            OutOperation = TEXT("anim_use_cached_pose");
            OutOwner = Blueprint ? Blueprint->GetPathName() : TEXT("");
            if (UAnimGraphNode_SaveCachedPose* CachedSavePose = UsePose->SaveCachedPoseNode.Get())
            {
                OutSymbol = CachedSavePose->CacheName;
                Semantic->SetStringField(TEXT("cache_name"), OutSymbol);
                Semantic->SetStringField(TEXT("save_node_guid"),
                    CachedSavePose->NodeGuid.ToString(EGuidFormats::DigitsWithHyphensLower));
            }
        }
        else if (UAnimGraphNode_LinkedAnimLayer* LinkedLayer = Cast<UAnimGraphNode_LinkedAnimLayer>(Node))
        {
            OutOperation = TEXT("anim_linked_layer");
            OutSymbol = LinkedLayer->Node.Layer.ToString();
            OutOwner = Blueprint ? Blueprint->GetPathName() : TEXT("");
            Semantic->SetStringField(TEXT("layer_name"), OutSymbol);
            Semantic->SetStringField(TEXT("interface_guid"),
                LinkedLayer->InterfaceGuid.ToString(EGuidFormats::DigitsWithHyphensLower));
        }
        else if (UAnimGraphNode_LinkedInputPose* LinkedInput = Cast<UAnimGraphNode_LinkedInputPose>(Node))
        {
            OutOperation = TEXT("anim_linked_input_pose");
            OutSymbol = LinkedInput->Node.Name.ToString();
            Semantic->SetStringField(TEXT("pose_name"), OutSymbol);
            Semantic->SetNumberField(TEXT("input_pose_index"), LinkedInput->InputPoseIndex);

            FString ReferenceSymbol;
            FString ReferenceOwner;
            AddMemberReferenceFields(
                LinkedInput->FunctionReference,
                SelfScope,
                Semantic,
                ReferenceSymbol,
                ReferenceOwner);
            OutOwner = ReferenceOwner;
            Semantic->SetStringField(TEXT("function_reference_name"), ReferenceSymbol);
        }
        else if (UAnimGraphNode_Slot* Slot = Cast<UAnimGraphNode_Slot>(Node))
        {
            OutOperation = TEXT("anim_slot");
            OutSymbol = Slot->Node.SlotName.ToString();
            OutOwner = Blueprint ? Blueprint->GetPathName() : TEXT("");
            Semantic->SetStringField(TEXT("slot_name"), OutSymbol);
            Semantic->SetBoolField(TEXT("always_update_source_pose"), Slot->Node.bAlwaysUpdateSourcePose);
        }
        else if (UAnimGraphNode_SequencePlayer* SequencePlayer = Cast<UAnimGraphNode_SequencePlayer>(Node))
        {
            OutOperation = TEXT("anim_sequence_player");
            if (UAnimationAsset* AnimationAsset = SequencePlayer->GetAnimationAsset())
            {
                OutSymbol = AnimationAsset->GetName();
                OutOwner = AnimationAsset->GetPathName();
                Semantic->SetStringField(TEXT("animation_asset"), AnimationAsset->GetPathName());
                Semantic->SetStringField(TEXT("animation_asset_class"),
                    AnimationAsset->GetClass()->GetPathName());
            }
        }
        else if (Cast<UAnimGraphNode_Root>(Node))
        {
            OutOperation = TEXT("anim_graph_root");
        }
        else if (Cast<UAnimGraphNode_TransitionResult>(Node))
        {
            OutOperation = TEXT("anim_transition_result");
        }
        else if (Cast<UAnimGraphNode_StateResult>(Node))
        {
            OutOperation = TEXT("anim_state_result");
        }

        // -----------------------------------------------------------------
        // Generic K2 graph semantics
        // -----------------------------------------------------------------
        else if (UK2Node_FunctionEntry* FunctionEntry = Cast<UK2Node_FunctionEntry>(Node))
        {
            OutOperation = TEXT("function_entry");
            AddMemberReferenceFields(
                FunctionEntry->FunctionReference,
                SelfScope,
                Semantic,
                OutSymbol,
                OutOwner);

            if (UFunction* SignatureFunction = FunctionEntry->FindSignatureFunction())
            {
                OutSymbol = SignatureFunction->GetName();
                if (UClass* OwnerClass = SignatureFunction->GetOwnerClass())
                {
                    OutOwner = OwnerClass->GetPathName();
                }
                Semantic->SetStringField(TEXT("resolved_function"), SignatureFunction->GetPathName());
            }
            Semantic->SetNumberField(TEXT("function_flags"), FunctionEntry->GetFunctionFlags());
            Semantic->SetNumberField(TEXT("local_variable_count"), FunctionEntry->LocalVariables.Num());
            TArray<TSharedPtr<FJsonValue>> LocalVariablesJson;
            for (const FBPVariableDescription& LocalVariable : FunctionEntry->LocalVariables)
            {
                const TSharedRef<FJsonObject> LocalJson = MakeShared<FJsonObject>();
                LocalJson->SetStringField(TEXT("name"), LocalVariable.VarName.ToString());
                LocalJson->SetStringField(TEXT("guid"), LocalVariable.VarGuid.ToString(EGuidFormats::DigitsWithHyphensLower));
                LocalJson->SetStringField(TEXT("default_value"), LocalVariable.DefaultValue);
                LocalJson->SetObjectField(TEXT("type"), PinTypeToJson(LocalVariable.VarType));
                LocalVariablesJson.Add(MakeShared<FJsonValueObject>(LocalJson));
            }
            Semantic->SetArrayField(TEXT("local_variables"), LocalVariablesJson);
            Semantic->SetStringField(TEXT("custom_generated_function_name"),
                FunctionEntry->CustomGeneratedFunctionName.ToString());
        }
        else if (UK2Node_FunctionResult* FunctionResult = Cast<UK2Node_FunctionResult>(Node))
        {
            OutOperation = TEXT("function_result");
            AddMemberReferenceFields(
                FunctionResult->FunctionReference,
                SelfScope,
                Semantic,
                OutSymbol,
                OutOwner);

            if (UFunction* SignatureFunction = FunctionResult->FindSignatureFunction())
            {
                OutSymbol = SignatureFunction->GetName();
                if (UClass* OwnerClass = SignatureFunction->GetOwnerClass())
                {
                    OutOwner = OwnerClass->GetPathName();
                }
                Semantic->SetStringField(TEXT("resolved_function"), SignatureFunction->GetPathName());
            }
        }
        else if (UK2Node_StructOperation* StructOperation = Cast<UK2Node_StructOperation>(Node))
        {
            // UK2Node_MakeStruct, UK2Node_BreakStruct, and
            // UK2Node_SetFieldsInStruct all inherit UK2Node_Variable through
            // UK2Node_StructOperation. Classify them before the generic
            // UK2Node_Variable fallback so they are not emitted as bogus
            // variable_reference nodes with member_name=None.
            if (Cast<UK2Node_SetFieldsInStruct>(Node))
            {
                OutOperation = TEXT("set_fields_in_struct");
            }
            else if (Cast<UK2Node_MakeStruct>(Node))
            {
                OutOperation = TEXT("make_struct");
            }
            else if (Cast<UK2Node_BreakStruct>(Node))
            {
                OutOperation = TEXT("break_struct");
            }
            else
            {
                OutOperation = TEXT("struct_operation");
            }

            if (UScriptStruct* StructType = StructOperation->StructType.Get())
            {
                OutSymbol = StructType->GetName();
                OutOwner = StructType->GetPathName();
                Semantic->SetStringField(TEXT("struct_type"), OutOwner);
                Semantic->SetStringField(TEXT("struct_name"), OutSymbol);
            }
            Semantic->SetBoolField(TEXT("pure"), StructOperation->IsNodePure());
            Semantic->SetStringField(TEXT("classification_source"), TEXT("node_class"));
            Semantic->SetStringField(TEXT("concrete_node_class"), Node->GetClass()->GetPathName());
        }
        else if (UK2Node_VariableGet* VariableGet = Cast<UK2Node_VariableGet>(Node))
        {
            OutOperation = TEXT("variable_get");
            AddMemberReferenceFields(VariableGet->VariableReference, SelfScope, Semantic, OutSymbol, OutOwner);
            if (UClass* SourceClass = VariableGet->GetVariableSourceClass())
            {
                OutOwner = SourceClass->GetPathName();
                Semantic->SetStringField(TEXT("variable_source_class"), OutOwner);
            }
        }
        else if (UK2Node_VariableSet* VariableSet = Cast<UK2Node_VariableSet>(Node))
        {
            OutOperation = TEXT("variable_set");
            AddMemberReferenceFields(VariableSet->VariableReference, SelfScope, Semantic, OutSymbol, OutOwner);
            if (UClass* SourceClass = VariableSet->GetVariableSourceClass())
            {
                OutOwner = SourceClass->GetPathName();
                Semantic->SetStringField(TEXT("variable_source_class"), OutOwner);
            }
        }
        else if (UK2Node_CallFunction* Call = Cast<UK2Node_CallFunction>(Node))
        {
            OutOperation = TEXT("function_call");
            AddMemberReferenceFields(Call->FunctionReference, SelfScope, Semantic, OutSymbol, OutOwner);

            // UE 5.8 deprecates bIsPureFunc/bIsConstFunc/bIsInterfaceCall.
            // Query the compiler-facing API and resolved reflection metadata instead.
            Semantic->SetBoolField(TEXT("pure"), Call->IsNodePure());

            UClass* ReferenceOwner = Call->FunctionReference.GetMemberParentClass(SelfScope);
            Semantic->SetBoolField(
                TEXT("interface_call"),
                ReferenceOwner && ReferenceOwner->HasAnyClassFlags(CLASS_Interface));

            if (UFunction* Function = Call->GetTargetFunction())
            {
                OutSymbol = Function->GetName();
                if (UClass* OwnerClass = Function->GetOwnerClass())
                {
                    OutOwner = OwnerClass->GetPathName();
                }
                Semantic->SetStringField(TEXT("resolved_function"), Function->GetPathName());
                Semantic->SetStringField(TEXT("function_name"), OutSymbol);
                Semantic->SetStringField(TEXT("function_owner"), OutOwner);
                Semantic->SetNumberField(TEXT("function_flags"), static_cast<double>(Function->FunctionFlags));
                Semantic->SetBoolField(TEXT("const"), Function->HasAnyFunctionFlags(FUNC_Const));
                Semantic->SetBoolField(TEXT("latent"), Call->IsLatentFunction());
            }
            else
            {
                Semantic->SetBoolField(TEXT("const"), false);
                Semantic->SetBoolField(TEXT("latent"), false);
            }
        }
        else if (UK2Node_CustomEvent* CustomEvent = Cast<UK2Node_CustomEvent>(Node))
        {
            OutOperation = TEXT("custom_event");
            OutSymbol = CustomEvent->CustomFunctionName.ToString();
            if (OutSymbol.IsEmpty())
            {
                AddMemberReferenceFields(CustomEvent->EventReference, SelfScope, Semantic, OutSymbol, OutOwner);
            }
            Semantic->SetStringField(TEXT("event_name"), OutSymbol);
            Semantic->SetBoolField(TEXT("call_in_editor"), CustomEvent->bCallInEditor);
            Semantic->SetBoolField(TEXT("deprecated"), CustomEvent->bIsDeprecated);
            Semantic->SetNumberField(TEXT("function_flags"), static_cast<double>(CustomEvent->FunctionFlags));
        }
        else if (UK2Node_Event* Event = Cast<UK2Node_Event>(Node))
        {
            OutOperation = TEXT("event");
            AddMemberReferenceFields(Event->EventReference, SelfScope, Semantic, OutSymbol, OutOwner);
            if (OutSymbol.IsEmpty())
            {
                OutSymbol = Event->CustomFunctionName.ToString();
            }
            Semantic->SetStringField(TEXT("event_name"), OutSymbol);
            Semantic->SetBoolField(TEXT("override_function"), Event->bOverrideFunction);
            Semantic->SetBoolField(TEXT("internal_event"), Event->bInternalEvent);
            Semantic->SetNumberField(TEXT("function_flags"), static_cast<double>(Event->FunctionFlags));
        }
        else if (UK2Node_DynamicCast* DynamicCast = Cast<UK2Node_DynamicCast>(Node))
        {
            OutOperation = TEXT("dynamic_cast");
            if (UClass* TargetClass = DynamicCast->TargetType.Get())
            {
                OutSymbol = TargetClass->GetName();
                OutOwner = TargetClass->GetPathName();
                Semantic->SetStringField(TEXT("target_class"), OutOwner);
            }
        }
        else if (UK2Node_SpawnActorFromClass* SpawnActor = Cast<UK2Node_SpawnActorFromClass>(Node))
        {
            OutOperation = TEXT("spawn_actor");
            if (UClass* SpawnClass = SpawnActor->GetClassToSpawn())
            {
                OutSymbol = SpawnClass->GetName();
                OutOwner = SpawnClass->GetPathName();
                Semantic->SetStringField(TEXT("spawn_class"), OutOwner);
                Semantic->SetBoolField(TEXT("dynamic_class"), false);
            }
            else
            {
                Semantic->SetBoolField(TEXT("dynamic_class"), true);
            }
        }
        else if (UK2Node_MacroInstance* Macro = Cast<UK2Node_MacroInstance>(Node))
        {
            OutOperation = TEXT("macro_instance");
            if (UEdGraph* MacroGraph = Macro->GetMacroGraph())
            {
                OutSymbol = MacroGraph->GetName();
                Semantic->SetStringField(TEXT("macro_graph"), MacroGraph->GetPathName());
            }
            if (UBlueprint* SourceBlueprint = Macro->GetSourceBlueprint())
            {
                OutOwner = SourceBlueprint->GetPathName();
                Semantic->SetStringField(TEXT("source_blueprint"), OutOwner);
            }
        }
        else if (UK2Node_Switch* SwitchNode = Cast<UK2Node_Switch>(Node))
        {
            OutOperation = TEXT("switch");
            OutSymbol = SwitchNode->GetClass()->GetName();
            Semantic->SetBoolField(TEXT("has_default_pin"), SwitchNode->bHasDefaultPin);
            Semantic->SetStringField(TEXT("function_name"), SwitchNode->FunctionName.ToString());
            if (UClass* FunctionOwner = SwitchNode->FunctionClass.Get())
            {
                Semantic->SetStringField(TEXT("function_class"), FunctionOwner->GetPathName());
            }
            if (UEdGraphPin* SelectionPin = SwitchNode->GetSelectionPin())
            {
                Semantic->SetObjectField(TEXT("selection_type"), PinTypeToJson(SelectionPin->PinType));
            }
        }
        else if (UK2Node_Select* Select = Cast<UK2Node_Select>(Node))
        {
            OutOperation = TEXT("select");
            Semantic->SetBoolField(TEXT("pure"), Select->IsNodePure());
        }
        else if (UK2Node_ExecutionSequence* Sequence = Cast<UK2Node_ExecutionSequence>(Node))
        {
            OutOperation = TEXT("execution_sequence");
            int32 OutputExecPins = 0;
            for (const UEdGraphPin* Pin : Sequence->Pins)
            {
                if (Pin && Pin->Direction == EGPD_Output && Pin->PinType.PinCategory == FName(TEXT("exec")))
                {
                    ++OutputExecPins;
                }
            }
            Semantic->SetNumberField(TEXT("output_exec_pins"), OutputExecPins);
        }
        else if (Cast<UK2Node_Knot>(Node))
        {
            OutOperation = TEXT("reroute");
        }
        else if (Cast<UK2Node_IfThenElse>(Node))
        {
            OutOperation = TEXT("branch");
        }
        else if (Cast<UK2Node_Tunnel>(Node))
        {
            OutOperation = TEXT("tunnel");
        }
        else if (Cast<UK2Node_Self>(Node))
        {
            OutOperation = TEXT("self");
            OutSymbol = TEXT("self");
            OutOwner = SelfScope ? SelfScope->GetPathName() : TEXT("");
        }
        else if (UEdGraphNode_Comment* Comment = Cast<UEdGraphNode_Comment>(Node))
        {
            OutOperation = TEXT("comment");
            OutSymbol = Comment->NodeComment;
            Semantic->SetStringField(TEXT("details"), Comment->NodeDetails.ToString());
            Semantic->SetNumberField(TEXT("font_size"), Comment->FontSize);
        }
        else if (UK2Node_Variable* Variable = Cast<UK2Node_Variable>(Node))
        {
            OutOperation = TEXT("variable_reference");
            AddMemberReferenceFields(Variable->VariableReference, SelfScope, Semantic, OutSymbol, OutOwner);
            if (UClass* SourceClass = Variable->GetVariableSourceClass())
            {
                OutOwner = SourceClass->GetPathName();
                Semantic->SetStringField(TEXT("variable_source_class"), OutOwner);
            }
        }

        ApplyClassSemanticFallback(Node, Semantic, OutOperation, OutSymbol, OutOwner);
        ApplyReflectedSemanticEnrichment(Blueprint, Node, Semantic, OutOperation, OutSymbol, OutOwner);

        Semantic->SetStringField(TEXT("operation"), OutOperation);
        Semantic->SetStringField(TEXT("symbol"), OutSymbol);
        Semantic->SetStringField(TEXT("owner"), OutOwner);
        return Semantic;
    }

    static bool ScanFiles(
        const FString& ProjectDir,
        const FString& ToolPluginDir,
        const FString& OutputDir,
        bool bIncludeGenerated,
        bool bIncludeSelf,
        FJsonlWriter& FilesWriter,
        FJsonlWriter& SourceWriter,
        FScanCounts& Counts)
    {
        TArray<FString> Files;
        IFileManager::Get().FindFilesRecursive(Files, *ProjectDir, TEXT("*"), true, false, false);
        Files.Sort();

        for (const FString& FullPathUnnormalized : Files)
        {
            const FString FullPath = NormalizeAbsolutePath(FullPathUnnormalized);
            FString RelativePath = FullPath;
            FPaths::MakePathRelativeTo(RelativePath, *ProjectDir);
            FPaths::NormalizeFilename(RelativePath);

            // The index describes the target project, not UnrealAssetTool itself.
            // Keep this separate from IncludeGenerated so generated/cache data can
            // be requested without also polluting the index with the scanner.
            if (!bIncludeSelf && !ToolPluginDir.IsEmpty() && IsInsideDirectory(FullPath, ToolPluginDir))
            {
                continue;
            }

            // Never index the output currently being produced, even when a custom
            // output directory name is used and IncludeGenerated is enabled.
            if (IsInsideDirectory(FullPath, OutputDir))
            {
                continue;
            }

            // A compact UnrealAssetTool result is scanner output, never project input.
            // Exclude it even with -IncludeGenerated so a previous scan cannot perturb
            // the next scan's physical-file count or source corpus.
            if (IsToolGeneratedPhysicalFile(RelativePath))
            {
                continue;
            }

            if (!bIncludeGenerated && IsGeneratedPath(RelativePath))
            {
                continue;
            }

            const int64 Size = IFileManager::Get().FileSize(*FullPath);
            const FDateTime Modified = IFileManager::Get().GetTimeStamp(*FullPath);

            const TSharedRef<FJsonObject> FileJson = MakeShared<FJsonObject>();
            FileJson->SetStringField(TEXT("path"), RelativePath);
            FileJson->SetStringField(TEXT("kind"), FileKind(RelativePath));
            FileJson->SetStringField(TEXT("extension"), FPaths::GetExtension(RelativePath, true).ToLower());
            FileJson->SetNumberField(TEXT("size"), static_cast<double>(Size));
            FileJson->SetStringField(TEXT("modified_utc"), Modified.ToIso8601());
            if (!FilesWriter.Write(FileJson))
            {
                return false;
            }
            ++Counts.Files;

            if (!IsTextFile(RelativePath))
            {
                continue;
            }

            FString Text;
            if (!FFileHelper::LoadFileToString(Text, *FullPath))
            {
                continue;
            }

            TArray<FString> Lines;
            Text.ParseIntoArrayLines(Lines, false);
            if (Lines.IsEmpty() && !Text.IsEmpty())
            {
                Lines.Add(Text);
            }

            for (int32 Start = 0; Start < Lines.Num(); Start += SourceChunkLines)
            {
                const int32 EndExclusive = FMath::Min(Start + SourceChunkLines, Lines.Num());
                FString Chunk;
                for (int32 LineIndex = Start; LineIndex < EndExclusive; ++LineIndex)
                {
                    if (!Chunk.IsEmpty())
                    {
                        Chunk.AppendChar(TEXT('\n'));
                    }
                    Chunk.Append(Lines[LineIndex]);
                }

                const TSharedRef<FJsonObject> ChunkJson = MakeShared<FJsonObject>();
                ChunkJson->SetStringField(TEXT("path"), RelativePath);
                ChunkJson->SetNumberField(TEXT("start_line"), Start + 1);
                ChunkJson->SetNumberField(TEXT("end_line"), EndExclusive);
                ChunkJson->SetStringField(TEXT("text"), Chunk);
                if (!SourceWriter.Write(ChunkJson))
                {
                    return false;
                }
                ++Counts.SourceChunks;
            }
        }
        return true;
    }


    static FString ExportStructFieldText(
        FStructProperty* StructProperty,
        void* StructValue,
        UObject* Owner,
        const FName FieldName)
    {
        if (!StructProperty || !StructProperty->Struct || !StructValue)
        {
            return TEXT("");
        }

        FProperty* Field = StructProperty->Struct->FindPropertyByName(FieldName);
        if (!Field)
        {
            return TEXT("");
        }

        const void* FieldValue = Field->ContainerPtrToValuePtr<void>(StructValue);
        FString Result;
        Field->ExportTextItem_Direct(
            Result,
            FieldValue,
            nullptr,
            Owner,
            PPF_None,
            nullptr);
        return Result;
    }

    static TArray<FString> ExportStructArrayFieldTexts(
        FStructProperty* StructProperty,
        void* StructValue,
        UObject* Owner,
        const FName FieldName)
    {
        TArray<FString> Result;
        if (!StructProperty || !StructProperty->Struct || !StructValue)
        {
            return Result;
        }

        FArrayProperty* ArrayProperty = CastField<FArrayProperty>(
            StructProperty->Struct->FindPropertyByName(FieldName));
        if (!ArrayProperty || !ArrayProperty->Inner)
        {
            return Result;
        }

        const void* ArrayValue = ArrayProperty->ContainerPtrToValuePtr<void>(StructValue);
        FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
        Result.Reserve(Helper.Num());

        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            FString Value;
            ArrayProperty->Inner->ExportTextItem_Direct(
                Value,
                Helper.GetRawPtr(Index),
                nullptr,
                Owner,
                PPF_None,
                nullptr);
            Result.Add(MoveTemp(Value));
        }
        return Result;
    }

    static bool ScanNodeBindings(
        UEdGraphNode* Node,
        const FString& NodeId,
        const FString& BlueprintPath,
        const FString& GraphName,
        FJsonlWriter& BindingsWriter,
        FScanCounts& Counts)
    {
        if (!Node)
        {
            return true;
        }

        UObject* BindingObject = GetReflectedObjectProperty(Node, TEXT("Binding"));
        if (!BindingObject)
        {
            return true;
        }

        FMapProperty* BindingsProperty = CastField<FMapProperty>(
            BindingObject->GetClass()->FindPropertyByName(TEXT("PropertyBindings")));
        if (!BindingsProperty || !BindingsProperty->KeyProp || !BindingsProperty->ValueProp)
        {
            return true;
        }

        FStructProperty* ValueStructProperty = CastField<FStructProperty>(BindingsProperty->ValueProp);
        if (!ValueStructProperty || !ValueStructProperty->Struct)
        {
            return true;
        }

        void* MapValue = BindingsProperty->ContainerPtrToValuePtr<void>(BindingObject);
        FScriptMapHelper Helper(BindingsProperty, MapValue);

        for (int32 Index = 0; Index < Helper.GetMaxIndex(); ++Index)
        {
            if (!Helper.IsValidIndex(Index))
            {
                continue;
            }

            void* KeyPtr = Helper.GetKeyPtr(Index);
            void* ValuePtr = Helper.GetValuePtr(Index);

            FString KeyText;
            BindingsProperty->KeyProp->ExportTextItem_Direct(
                KeyText,
                KeyPtr,
                nullptr,
                BindingObject,
                PPF_None,
                nullptr);

            FString RawValue;
            BindingsProperty->ValueProp->ExportTextItem_Direct(
                RawValue,
                ValuePtr,
                nullptr,
                BindingObject,
                PPF_None,
                nullptr);

            const FString PropertyName = ExportStructFieldText(
                ValueStructProperty, ValuePtr, BindingObject, TEXT("PropertyName"));
            const FString PathAsText = ExportStructFieldText(
                ValueStructProperty, ValuePtr, BindingObject, TEXT("PathAsText"));
            const FString CompiledContext = ExportStructFieldText(
                ValueStructProperty, ValuePtr, BindingObject, TEXT("CompiledContext"));
            const FString PinType = ExportStructFieldText(
                ValueStructProperty, ValuePtr, BindingObject, TEXT("PinType"));
            const FString PromotedPinType = ExportStructFieldText(
                ValueStructProperty, ValuePtr, BindingObject, TEXT("PromotedPinType"));
            const TArray<FString> PropertyPath = ExportStructArrayFieldTexts(
                ValueStructProperty, ValuePtr, BindingObject, TEXT("PropertyPath"));

            TArray<TSharedPtr<FJsonValue>> PathJson;
            PathJson.Reserve(PropertyPath.Num());
            for (const FString& Segment : PropertyPath)
            {
                PathJson.Add(MakeShared<FJsonValueString>(Segment));
            }

            const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
            Json->SetStringField(TEXT("node_id"), NodeId);
            Json->SetStringField(TEXT("blueprint_path"), BlueprintPath);
            Json->SetStringField(TEXT("graph_name"), GraphName);
            Json->SetStringField(TEXT("node_class"), Node->GetClass()->GetPathName());
            Json->SetStringField(TEXT("binding_object"), BindingObject->GetPathName());
            Json->SetStringField(TEXT("binding_key"), KeyText);
            Json->SetStringField(TEXT("target_property"), PropertyName.IsEmpty() ? KeyText : PropertyName);
            Json->SetStringField(TEXT("access_path"), PathAsText);
            Json->SetArrayField(TEXT("property_path"), PathJson);
            Json->SetStringField(TEXT("compiled_context"), CompiledContext);
            Json->SetStringField(TEXT("pin_type"), PinType);
            Json->SetStringField(TEXT("promoted_pin_type"), PromotedPinType);
            Json->SetStringField(TEXT("raw_value"), RawValue);

            if (!BindingsWriter.Write(Json))
            {
                return false;
            }
            ++Counts.BlueprintBindings;
        }

        return true;
    }

    static bool ClassIsOrDerivedFromName(const UClass* Class, const FName BaseClassName)
    {
        for (const UClass* Current = Class; Current; Current = Current->GetSuperClass())
        {
            if (Current->GetFName() == BaseClassName)
            {
                return true;
            }
        }
        return false;
    }

    static FString RigVMObjectKind(UObject* Object)
    {
        if (!Object)
        {
            return TEXT("");
        }

        UClass* Class = Object->GetClass();
        if (ClassIsOrDerivedFromName(Class, TEXT("RigVMGraph"))) return TEXT("graph");
        if (ClassIsOrDerivedFromName(Class, TEXT("RigVMNode"))) return TEXT("node");
        if (ClassIsOrDerivedFromName(Class, TEXT("RigVMPin"))) return TEXT("pin");
        if (ClassIsOrDerivedFromName(Class, TEXT("RigVMLink"))) return TEXT("link");
        return TEXT("");
    }

    static FString RigVMNodeOperation(UObject* Object)
    {
        if (!Object || !ClassIsOrDerivedFromName(Object->GetClass(), TEXT("RigVMNode")))
        {
            return TEXT("");
        }

        struct FRigVMClassSemantic
        {
            const TCHAR* ClassName;
            const TCHAR* Operation;
        };

        static const FRigVMClassSemantic Classes[] =
        {
            { TEXT("RigVMFunctionEntryNode"), TEXT("rigvm_function_entry") },
            { TEXT("RigVMFunctionReturnNode"), TEXT("rigvm_function_return") },
            { TEXT("RigVMFunctionReferenceNode"), TEXT("rigvm_function_reference") },
            { TEXT("RigVMVariableNode"), TEXT("rigvm_variable") },
            { TEXT("RigVMUnitNode"), TEXT("rigvm_unit") },
            { TEXT("RigVMDispatchNode"), TEXT("rigvm_dispatch") },
            { TEXT("RigVMInvokeEntryNode"), TEXT("rigvm_invoke_entry") },
            { TEXT("RigVMRerouteNode"), TEXT("rigvm_reroute") },
            { TEXT("RigVMEnumNode"), TEXT("rigvm_enum") },
            { TEXT("RigVMCommentNode"), TEXT("rigvm_comment") },
            { TEXT("RigVMParameterNode"), TEXT("rigvm_parameter") },
            { TEXT("RigVMLibraryNode"), TEXT("rigvm_library") },
            { TEXT("RigVMTemplateNode"), TEXT("rigvm_template") }
        };

        for (const FRigVMClassSemantic& Entry : Classes)
        {
            if (ClassIsOrDerivedFromName(Object->GetClass(), FName(Entry.ClassName)))
            {
                return Entry.Operation;
            }
        }
        return TEXT("rigvm_node");
    }

    static bool WriteRigVMReference(
        UObject* SourceObject,
        UObject* TargetObject,
        const FString& BlueprintPath,
        const FString& PropertyPath,
        FJsonlWriter& ReferencesWriter,
        FScanCounts& Counts)
    {
        if (!SourceObject || !TargetObject)
        {
            return true;
        }

        const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
        Json->SetStringField(TEXT("source_object_id"), SourceObject->GetPathName());
        Json->SetStringField(TEXT("blueprint_path"), BlueprintPath);
        Json->SetStringField(TEXT("source_kind"), RigVMObjectKind(SourceObject));
        Json->SetStringField(TEXT("source_class"), SourceObject->GetClass()->GetPathName());
        Json->SetStringField(TEXT("property_path"), PropertyPath);
        Json->SetStringField(TEXT("target_object_id"), TargetObject->GetPathName());
        Json->SetStringField(TEXT("target_kind"), RigVMObjectKind(TargetObject));
        Json->SetStringField(TEXT("target_class"), TargetObject->GetClass()->GetPathName());

        if (!ReferencesWriter.Write(Json))
        {
            return false;
        }
        ++Counts.RigVMReferences;
        return true;
    }

    static bool ScanRigVMObjectProperties(
        UObject* Object,
        const FString& BlueprintPath,
        FJsonlWriter& PropertiesWriter,
        FScanCounts& Counts)
    {
        if (!Object)
        {
            return true;
        }

        static constexpr int32 MaxExportedPropertyChars = 65536;
        const FString Kind = RigVMObjectKind(Object);

        for (UClass* Class = Object->GetClass();
             Class && Class != UObject::StaticClass();
             Class = Class->GetSuperClass())
        {
            for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
            {
                FProperty* Property = *It;
                if (!IsCapturableProperty(Property))
                {
                    continue;
                }

                const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
                FString Value;
                Property->ExportTextItem_Direct(
                    Value,
                    ValuePtr,
                    nullptr,
                    Object,
                    PPF_None,
                    nullptr);

                bool bTruncated = false;
                if (Value.Len() > MaxExportedPropertyChars)
                {
                    Value = Value.Left(MaxExportedPropertyChars);
                    bTruncated = true;
                }

                FString ObjectPath;
                FString ObjectClass;
                UObject* ObjectValue = nullptr;
                if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
                {
                    ObjectValue = ObjectProperty->GetObjectPropertyValue(ValuePtr);
                    if (ObjectValue)
                    {
                        ObjectPath = ObjectValue->GetPathName();
                        ObjectClass = ObjectValue->GetClass()->GetPathName();
                    }
                }

                const TSharedRef<FJsonObject> PropertyJson = MakeShared<FJsonObject>();
                PropertyJson->SetStringField(TEXT("object_id"), Object->GetPathName());
                PropertyJson->SetStringField(TEXT("blueprint_path"), BlueprintPath);
                PropertyJson->SetStringField(TEXT("kind"), Kind);
                PropertyJson->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
                PropertyJson->SetStringField(TEXT("declaring_type"), Class->GetPathName());
                PropertyJson->SetStringField(TEXT("property_name"), Property->GetName());
                PropertyJson->SetStringField(TEXT("property_path"), Property->GetName());
                PropertyJson->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
                PropertyJson->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
                PropertyJson->SetStringField(TEXT("value"), Value);
                PropertyJson->SetStringField(TEXT("object_path"), ObjectPath);
                PropertyJson->SetStringField(TEXT("object_class"), ObjectClass);
                PropertyJson->SetNumberField(TEXT("property_flags"), static_cast<double>(Property->GetPropertyFlags()));
                PropertyJson->SetBoolField(TEXT("truncated"), bTruncated);

                if (!PropertiesWriter.Write(PropertyJson))
                {
                    return false;
                }
                ++Counts.RigVMProperties;

            }
        }

        return true;
    }

    static bool ScanRigVMObjectReferences(
        UObject* Object,
        const FString& BlueprintPath,
        FJsonlWriter& ReferencesWriter,
        FScanCounts& Counts)
    {
        if (!Object)
        {
            return true;
        }

        for (UClass* Class = Object->GetClass();
             Class && Class != UObject::StaticClass();
             Class = Class->GetSuperClass())
        {
            for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
            {
                FProperty* Property = *It;
                if (!IsCapturableProperty(Property))
                {
                    continue;
                }

                const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
                if (FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
                {
                    if (UObject* Target = ObjectProperty->GetObjectPropertyValue(ValuePtr))
                    {
                        if (!WriteRigVMReference(
                                Object,
                                Target,
                                BlueprintPath,
                                Property->GetName(),
                                ReferencesWriter,
                                Counts))
                        {
                            return false;
                        }
                    }
                    continue;
                }

                FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property);
                FObjectPropertyBase* InnerObjectProperty = ArrayProperty
                    ? CastField<FObjectPropertyBase>(ArrayProperty->Inner)
                    : nullptr;
                if (!ArrayProperty || !InnerObjectProperty)
                {
                    continue;
                }

                FScriptArrayHelper Helper(ArrayProperty, ValuePtr);
                for (int32 Index = 0; Index < Helper.Num(); ++Index)
                {
                    UObject* Target = InnerObjectProperty->GetObjectPropertyValue(Helper.GetRawPtr(Index));
                    if (!Target)
                    {
                        continue;
                    }
                    const FString ElementPath = FString::Printf(TEXT("%s[%d]"), *Property->GetName(), Index);
                    if (!WriteRigVMReference(
                            Object,
                            Target,
                            BlueprintPath,
                            ElementPath,
                            ReferencesWriter,
                            Counts))
                    {
                        return false;
                    }
                }
            }
        }

        return true;
    }

    static bool ScanRigVMObjects(
        UBlueprint* Blueprint,
        const FString& BlueprintPath,
        FJsonlWriter& ObjectsWriter,
        FJsonlWriter& PinsWriter,
        FJsonlWriter& LinksWriter,
        FJsonlWriter& PropertiesWriter,
        FJsonlWriter& ReferencesWriter,
        bool bIncludeRawProperties,
        FScanCounts& Counts)
    {
        if (!Blueprint)
        {
            return true;
        }

        TArray<UObject*> OwnedObjects;
        GetObjectsWithOuter(Blueprint, OwnedObjects, EGetObjectsFlags::IncludeNestedObjects);

        for (UObject* Object : OwnedObjects)
        {
            const FString Kind = RigVMObjectKind(Object);
            if (Kind.IsEmpty())
            {
                continue;
            }

            if (Kind == TEXT("graph") || Kind == TEXT("node"))
            {
                const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
                Json->SetStringField(TEXT("object_id"), Object->GetPathName());
                Json->SetStringField(TEXT("blueprint_path"), BlueprintPath);
                Json->SetStringField(TEXT("kind"), Kind);
                Json->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
                Json->SetStringField(TEXT("name"), Object->GetName());
                Json->SetStringField(TEXT("outer_object_id"), Object->GetOuter() ? Object->GetOuter()->GetPathName() : TEXT(""));
                Json->SetStringField(TEXT("outer_class"), Object->GetOuter() ? Object->GetOuter()->GetClass()->GetPathName() : TEXT(""));
                Json->SetStringField(TEXT("operation"), Kind == TEXT("node") ? RigVMNodeOperation(Object) : TEXT(""));

                if (Kind == TEXT("graph"))
                {
                    Json->SetStringField(TEXT("editable"), ExportReflectedPropertyText(Object, TEXT("bEditable")));
                    if (UObject* ExecuteContext = GetReflectedObjectProperty(Object, TEXT("ExecuteContextStruct")))
                    {
                        Json->SetStringField(TEXT("execute_context_struct"), ExecuteContext->GetPathName());
                    }
                }
                else
                {
                    Json->SetStringField(TEXT("node_title"), ExportReflectedPropertyText(Object, TEXT("NodeTitle")));
                    Json->SetStringField(TEXT("position"), ExportReflectedPropertyText(Object, TEXT("Position")));
                    Json->SetStringField(TEXT("template_notation"), ExportReflectedPropertyText(Object, TEXT("TemplateNotation")));
                    Json->SetStringField(TEXT("resolved_function_name"), ExportReflectedPropertyText(Object, TEXT("ResolvedFunctionName")));
                    Json->SetStringField(TEXT("variable_guid"), ExportReflectedPropertyText(Object, TEXT("VariableGuid")));
                    if (UObject* ContainedGraph = GetReflectedObjectProperty(Object, TEXT("ContainedGraph")))
                    {
                        Json->SetStringField(TEXT("contained_graph"), ContainedGraph->GetPathName());
                    }
                }

                if (!ObjectsWriter.Write(Json))
                {
                    return false;
                }
                ++Counts.RigVMObjects;
            }
            else if (Kind == TEXT("pin"))
            {
                const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
                Json->SetStringField(TEXT("pin_id"), Object->GetPathName());
                Json->SetStringField(TEXT("blueprint_path"), BlueprintPath);
                Json->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
                Json->SetStringField(TEXT("name"), Object->GetName());
                Json->SetStringField(TEXT("outer_object_id"), Object->GetOuter() ? Object->GetOuter()->GetPathName() : TEXT(""));
                Json->SetStringField(TEXT("display_name"), ExportReflectedPropertyText(Object, TEXT("DisplayName")));
                Json->SetStringField(TEXT("direction"), ExportReflectedPropertyText(Object, TEXT("Direction")));
                Json->SetStringField(TEXT("cpp_type"), ExportReflectedPropertyText(Object, TEXT("CPPType")));
                Json->SetStringField(TEXT("cpp_type_object_path"), ExportReflectedPropertyText(Object, TEXT("CPPTypeObjectPath")));
                Json->SetStringField(TEXT("default_value"), ExportReflectedPropertyText(Object, TEXT("DefaultValue")));
                Json->SetStringField(TEXT("default_value_type"), ExportReflectedPropertyText(Object, TEXT("DefaultValueType")));
                Json->SetStringField(TEXT("custom_widget_name"), ExportReflectedPropertyText(Object, TEXT("CustomWidgetName")));
                Json->SetStringField(TEXT("is_constant"), ExportReflectedPropertyText(Object, TEXT("bIsConstant")));
                Json->SetStringField(TEXT("is_input_variable"), ExportReflectedPropertyText(Object, TEXT("bIsInputVariable")));
                Json->SetStringField(TEXT("is_dynamic_array"), ExportReflectedPropertyText(Object, TEXT("bIsDynamicArray")));
                Json->SetStringField(TEXT("is_lazy"), ExportReflectedPropertyText(Object, TEXT("bIsLazy")));
                if (UObject* CPPTypeObject = GetReflectedObjectProperty(Object, TEXT("CPPTypeObject")))
                {
                    Json->SetStringField(TEXT("cpp_type_object"), CPPTypeObject->GetPathName());
                }
                if (UObject* DefaultValueObject = GetReflectedObjectProperty(Object, TEXT("DefaultValueObject")))
                {
                    Json->SetStringField(TEXT("default_value_object"), DefaultValueObject->GetPathName());
                }
                if (!PinsWriter.Write(Json))
                {
                    return false;
                }
                ++Counts.RigVMPins;
            }
            else if (Kind == TEXT("link"))
            {
                const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
                Json->SetStringField(TEXT("link_id"), Object->GetPathName());
                Json->SetStringField(TEXT("blueprint_path"), BlueprintPath);
                Json->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
                Json->SetStringField(TEXT("source_pin_path"), ExportReflectedPropertyText(Object, TEXT("SourcePinPath")));
                Json->SetStringField(TEXT("target_pin_path"), ExportReflectedPropertyText(Object, TEXT("TargetPinPath")));
                if (!LinksWriter.Write(Json))
                {
                    return false;
                }
                ++Counts.RigVMLinks;
            }

            if (!ScanRigVMObjectReferences(Object, BlueprintPath, ReferencesWriter, Counts))
            {
                return false;
            }

            if (bIncludeRawProperties &&
                !ScanRigVMObjectProperties(Object, BlueprintPath, PropertiesWriter, Counts))
            {
                return false;
            }
        }

        return true;
    }


    static FString ExportPropertyTextInContainer(
        FProperty* Property,
        const void* Container,
        UObject* OwnerObject,
        int32 ArrayIndex = 0,
        int32 MaxChars = 65536)
    {
        if (!Property || !Container)
        {
            return TEXT("");
        }

        FString Value;
        Property->ExportText_InContainer(
            ArrayIndex,
            Value,
            Container,
            nullptr,
            OwnerObject,
            PPF_None,
            nullptr);

        if (MaxChars > 0 && Value.Len() > MaxChars)
        {
            Value = Value.Left(MaxChars);
        }
        return Value;
    }

    static UObject* GetObjectPropertyValueInContainer(
        FProperty* Property,
        const void* Container,
        int32 ArrayIndex = 0)
    {
        if (!Property || !Container)
        {
            return nullptr;
        }

        const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property);
        if (!ObjectProperty)
        {
            return nullptr;
        }

        const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Container, ArrayIndex);
        return ValuePtr ? ObjectProperty->GetObjectPropertyValue(ValuePtr) : nullptr;
    }

    static void GetReflectedObjectArray(
        UObject* Object,
        const FName PropertyName,
        TArray<UObject*>& OutObjects)
    {
        if (!Object)
        {
            return;
        }

        FArrayProperty* ArrayProperty = CastField<FArrayProperty>(
            Object->GetClass()->FindPropertyByName(PropertyName));
        if (!ArrayProperty)
        {
            return;
        }

        FObjectPropertyBase* InnerObject = CastField<FObjectPropertyBase>(ArrayProperty->Inner);
        if (!InnerObject)
        {
            return;
        }

        const void* ArrayValue = ArrayProperty->ContainerPtrToValuePtr<void>(Object);
        if (!ArrayValue)
        {
            return;
        }

        FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
        OutObjects.Reserve(OutObjects.Num() + Helper.Num());
        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            const void* ElementValue = Helper.GetRawPtr(Index);
            if (UObject* Value = InnerObject->GetObjectPropertyValue(ElementValue))
            {
                OutObjects.Add(Value);
            }
        }
    }

    static FString ExportStructFieldText(
        UStruct* Struct,
        const void* StructValue,
        const FName FieldName,
        UObject* OwnerObject,
        int32 MaxChars = 16384)
    {
        if (!Struct || !StructValue)
        {
            return TEXT("");
        }

        FProperty* Field = Struct->FindPropertyByName(FieldName);
        if (!Field)
        {
            return TEXT("");
        }

        const void* FieldValue = Field->ContainerPtrToValuePtr<void>(StructValue);
        if (!FieldValue)
        {
            return TEXT("");
        }

        FString Value;
        Field->ExportTextItem_Direct(Value, FieldValue, nullptr, OwnerObject, PPF_None, nullptr);
        if (MaxChars > 0 && Value.Len() > MaxChars)
        {
            Value = Value.Left(MaxChars);
        }
        return Value;
    }

    static UObject* GetStructObjectField(
        UStruct* Struct,
        const void* StructValue,
        const FName FieldName)
    {
        if (!Struct || !StructValue)
        {
            return nullptr;
        }

        FObjectPropertyBase* Field = CastField<FObjectPropertyBase>(
            Struct->FindPropertyByName(FieldName));
        if (!Field)
        {
            return nullptr;
        }

        const void* FieldValue = Field->ContainerPtrToValuePtr<void>(StructValue);
        return FieldValue ? Field->GetObjectPropertyValue(FieldValue) : nullptr;
    }


    struct FChangedValueScanContext
    {
        FString BlueprintPath;
        FString OwnerKind;
        FString OwnerId;
        FString OwnerName;
        FString OwnerClass;
        FString BaselineClass;
        FJsonlWriter* Writer = nullptr;
        int64* Counter = nullptr;
        UObject* ExportOwner = nullptr;
        UObject* BaselineExportOwner = nullptr;
    };

    static FString ChangedValueContainerKind(const FProperty* Property)
    {
        if (CastField<FStructProperty>(Property))
        {
            return TEXT("struct");
        }
        if (CastField<FArrayProperty>(Property))
        {
            return TEXT("array");
        }
        if (CastField<FMapProperty>(Property))
        {
            return TEXT("map");
        }
        if (CastField<FSetProperty>(Property))
        {
            return TEXT("set");
        }
        if (CastField<FObjectPropertyBase>(Property))
        {
            return TEXT("object");
        }
        return TEXT("scalar");
    }

    static FString ExportPropertyTextDirect(
        FProperty* Property,
        const void* ValuePtr,
        UObject* OwnerObject,
        int32 MaxChars,
        bool& bOutTruncated)
    {
        bOutTruncated = false;
        if (!Property || !ValuePtr)
        {
            return TEXT("");
        }

        FString Value;
        Property->ExportTextItem_Direct(
            Value,
            ValuePtr,
            nullptr,
            OwnerObject,
            PPF_None,
            nullptr);

        if (MaxChars > 0 && Value.Len() > MaxChars)
        {
            Value = Value.Left(MaxChars);
            bOutTruncated = true;
        }
        return Value;
    }

    static UObject* GetObjectPropertyValueDirect(
        FProperty* Property,
        const void* ValuePtr)
    {
        const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property);
        return ObjectProperty && ValuePtr
            ? ObjectProperty->GetObjectPropertyValue(ValuePtr)
            : nullptr;
    }

    static bool WriteChangedValueRecord(
        FChangedValueScanContext& Context,
        FProperty* Property,
        const void* CurrentValue,
        const void* BaselineValue,
        const FString& RootProperty,
        const FString& PropertyPath,
        int32 Depth)
    {
        if (!Context.Writer || !Context.Counter || !Property || !CurrentValue)
        {
            return true;
        }

        bool bValueTruncated = false;
        bool bBaselineTruncated = false;
        const FString Value = ExportPropertyTextDirect(
            Property, CurrentValue, Context.ExportOwner, 16384, bValueTruncated);
        const FString BaselineText = BaselineValue
            ? ExportPropertyTextDirect(
                Property, BaselineValue, Context.BaselineExportOwner, 16384, bBaselineTruncated)
            : TEXT("");

        UObject* ObjectValue = GetObjectPropertyValueDirect(Property, CurrentValue);
        UObject* BaselineObjectValue = BaselineValue
            ? GetObjectPropertyValueDirect(Property, BaselineValue)
            : nullptr;

        const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
        Json->SetStringField(TEXT("blueprint_path"), Context.BlueprintPath);
        Json->SetStringField(TEXT("owner_kind"), Context.OwnerKind);
        Json->SetStringField(TEXT("owner_id"), Context.OwnerId);
        Json->SetStringField(TEXT("owner_name"), Context.OwnerName);
        Json->SetStringField(TEXT("owner_class"), Context.OwnerClass);
        Json->SetStringField(TEXT("baseline_class"), Context.BaselineClass);
        Json->SetStringField(TEXT("root_property"), RootProperty);
        Json->SetStringField(TEXT("property_name"), Property->GetName());
        Json->SetStringField(TEXT("property_path"), PropertyPath);
        Json->SetNumberField(TEXT("depth"), Depth);
        Json->SetStringField(TEXT("container_kind"), ChangedValueContainerKind(Property));
        Json->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
        Json->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
        Json->SetStringField(TEXT("value"), Value);
        Json->SetStringField(TEXT("baseline_value"), BaselineText);
        Json->SetBoolField(TEXT("baseline_present"), BaselineValue != nullptr);
        Json->SetStringField(
            TEXT("referenced_object_path"),
            ObjectValue ? ObjectValue->GetPathName() : TEXT(""));
        Json->SetStringField(
            TEXT("referenced_object_class"),
            ObjectValue ? ObjectValue->GetClass()->GetPathName() : TEXT(""));
        Json->SetStringField(
            TEXT("baseline_object_path"),
            BaselineObjectValue ? BaselineObjectValue->GetPathName() : TEXT(""));
        Json->SetStringField(
            TEXT("baseline_object_class"),
            BaselineObjectValue ? BaselineObjectValue->GetClass()->GetPathName() : TEXT(""));
        Json->SetNumberField(
            TEXT("property_flags"),
            static_cast<double>(Property->GetPropertyFlags()));
        Json->SetBoolField(TEXT("truncated"), bValueTruncated || bBaselineTruncated);

        if (!Context.Writer->Write(Json))
        {
            return false;
        }
        ++(*Context.Counter);
        return true;
    }

    static bool ScanChangedValueDirect(
        FChangedValueScanContext& Context,
        FProperty* Property,
        const void* CurrentValue,
        const void* BaselineValue,
        const FString& RootProperty,
        const FString& PropertyPath,
        int32 Depth)
    {
        if (!Property || !CurrentValue || !IsCapturableProperty(Property))
        {
            return true;
        }

        static constexpr int32 MaxDepth = 4;
        static constexpr int32 MaxArrayElements = 64;

        if (BaselineValue && Property->Identical(CurrentValue, BaselineValue, PPF_None))
        {
            return true;
        }

        if (!WriteChangedValueRecord(
                Context,
                Property,
                CurrentValue,
                BaselineValue,
                RootProperty,
                PropertyPath,
                Depth))
        {
            return false;
        }

        if (Depth >= MaxDepth)
        {
            return true;
        }

        if (FStructProperty* StructProperty = CastField<FStructProperty>(Property))
        {
            if (!StructProperty->Struct)
            {
                return true;
            }

            for (TFieldIterator<FProperty> It(
                     StructProperty->Struct,
                     EFieldIterationFlags::Default);
                 It;
                 ++It)
            {
                FProperty* Child = *It;
                if (!IsCapturableProperty(Child))
                {
                    continue;
                }

                for (int32 ChildArrayIndex = 0;
                     ChildArrayIndex < Child->ArrayDim;
                     ++ChildArrayIndex)
                {
                    const void* ChildCurrent =
                        Child->ContainerPtrToValuePtr<void>(CurrentValue, ChildArrayIndex);
                    const void* ChildBaseline = BaselineValue
                        ? Child->ContainerPtrToValuePtr<void>(BaselineValue, ChildArrayIndex)
                        : nullptr;

                    FString ChildPath = FString::Printf(
                        TEXT("%s.%s"),
                        *PropertyPath,
                        *Child->GetName());
                    if (Child->ArrayDim > 1)
                    {
                        ChildPath += FString::Printf(TEXT("[%d]"), ChildArrayIndex);
                    }

                    if (!ScanChangedValueDirect(
                            Context,
                            Child,
                            ChildCurrent,
                            ChildBaseline,
                            RootProperty,
                            ChildPath,
                            Depth + 1))
                    {
                        return false;
                    }
                }
            }
        }
        else if (FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
        {
            if (!ArrayProperty->Inner)
            {
                return true;
            }

            FScriptArrayHelper CurrentHelper(ArrayProperty, CurrentValue);
            TUniquePtr<FScriptArrayHelper> BaselineHelper;
            if (BaselineValue)
            {
                BaselineHelper = MakeUnique<FScriptArrayHelper>(
                    ArrayProperty,
                    BaselineValue);
            }

            const int32 NumToScan = FMath::Min(CurrentHelper.Num(), MaxArrayElements);
            for (int32 Index = 0; Index < NumToScan; ++Index)
            {
                const void* ElementCurrent = CurrentHelper.GetRawPtr(Index);
                const void* ElementBaseline =
                    BaselineHelper.IsValid() && Index < BaselineHelper->Num()
                    ? BaselineHelper->GetRawPtr(Index)
                    : nullptr;

                const FString ElementPath = FString::Printf(
                    TEXT("%s[%d]"),
                    *PropertyPath,
                    Index);

                if (!ScanChangedValueDirect(
                        Context,
                        ArrayProperty->Inner,
                        ElementCurrent,
                        ElementBaseline,
                        RootProperty,
                        ElementPath,
                        Depth + 1))
                {
                    return false;
                }
            }
        }

        return true;
    }

    static bool ScanChangedPropertyInContainers(
        FChangedValueScanContext& Context,
        FProperty* Property,
        const void* CurrentContainer,
        const void* BaselineContainer,
        int32 ArrayIndex)
    {
        if (!Property || !CurrentContainer)
        {
            return true;
        }

        const void* CurrentValue =
            Property->ContainerPtrToValuePtr<void>(CurrentContainer, ArrayIndex);
        const void* BaselineValue = BaselineContainer
            ? Property->ContainerPtrToValuePtr<void>(BaselineContainer, ArrayIndex)
            : nullptr;

        FString RootPath = Property->GetName();
        if (Property->ArrayDim > 1)
        {
            RootPath += FString::Printf(TEXT("[%d]"), ArrayIndex);
        }

        return ScanChangedValueDirect(
            Context,
            Property,
            CurrentValue,
            BaselineValue,
            Property->GetName(),
            RootPath,
            0);
    }

    static bool ScanBlueprintDefaults(
        UBlueprint* Blueprint,
        const FString& BlueprintPath,
        FJsonlWriter& DefaultsWriter,
        FJsonlWriter& StateValuesWriter,
        FScanCounts& Counts)
    {
        if (!Blueprint || !Blueprint->GeneratedClass)
        {
            return true;
        }

        UClass* GeneratedClass = Blueprint->GeneratedClass;
        UObject* CDO = GeneratedClass->GetDefaultObject();
        UObject* ParentCDO = Blueprint->ParentClass ? Blueprint->ParentClass->GetDefaultObject() : nullptr;
        if (!CDO)
        {
            return true;
        }

        static constexpr uint64 SkipFlags =
            CPF_Transient | CPF_DuplicateTransient | CPF_NonPIEDuplicateTransient | CPF_Deprecated;

        for (TFieldIterator<FProperty> It(GeneratedClass, EFieldIterationFlags::IncludeSuper); It; ++It)
        {
            FProperty* Property = *It;
            if (!Property || Property->HasAnyPropertyFlags(SkipFlags))
            {
                continue;
            }

            const UClass* DeclaringClass = Property->GetOwnerClass();
            const bool bDeclaredHere = DeclaringClass == GeneratedClass;
            const bool bCanCompareToParent =
                ParentCDO &&
                Blueprint->ParentClass &&
                Property->IsInContainer(Blueprint->ParentClass);

            for (int32 ArrayIndex = 0; ArrayIndex < Property->ArrayDim; ++ArrayIndex)
            {
                const bool bDifferent =
                    !bCanCompareToParent ||
                    !Property->Identical_InContainer(CDO, ParentCDO, ArrayIndex, PPF_None);
                if (!bDifferent)
                {
                    continue;
                }

                const FString Value = ExportPropertyTextInContainer(
                    Property, CDO, CDO, ArrayIndex, 65536);
                const FString ParentValue = bCanCompareToParent
                    ? ExportPropertyTextInContainer(Property, ParentCDO, ParentCDO, ArrayIndex, 65536)
                    : TEXT("");

                UObject* ObjectValue = GetObjectPropertyValueInContainer(
                    Property, CDO, ArrayIndex);

                const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
                Json->SetStringField(TEXT("blueprint_path"), BlueprintPath);
                Json->SetStringField(TEXT("class_path"), GeneratedClass->GetPathName());
                Json->SetStringField(TEXT("property_name"), Property->GetName());
                Json->SetStringField(
                    TEXT("declaring_class"),
                    DeclaringClass ? DeclaringClass->GetPathName() : TEXT(""));
                Json->SetNumberField(TEXT("array_index"), ArrayIndex);
                Json->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
                Json->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
                Json->SetStringField(TEXT("value"), Value);
                Json->SetStringField(TEXT("parent_value"), ParentValue);
                Json->SetStringField(
                    TEXT("referenced_object_path"),
                    ObjectValue ? ObjectValue->GetPathName() : TEXT(""));
                Json->SetStringField(
                    TEXT("referenced_object_class"),
                    ObjectValue ? ObjectValue->GetClass()->GetPathName() : TEXT(""));
                Json->SetBoolField(TEXT("declared_here"), bDeclaredHere);
                Json->SetNumberField(
                    TEXT("property_flags"),
                    static_cast<double>(Property->GetPropertyFlags()));

                if (!DefaultsWriter.Write(Json))
                {
                    return false;
                }
                ++Counts.BlueprintDefaults;

                FChangedValueScanContext StateContext;
                StateContext.BlueprintPath = BlueprintPath;
                StateContext.OwnerKind = TEXT("class_default");
                StateContext.OwnerId = GeneratedClass->GetPathName();
                StateContext.OwnerName = GeneratedClass->GetName();
                StateContext.OwnerClass = GeneratedClass->GetPathName();
                StateContext.BaselineClass = Blueprint->ParentClass
                    ? Blueprint->ParentClass->GetPathName()
                    : TEXT("");
                StateContext.Writer = &StateValuesWriter;
                StateContext.Counter = &Counts.BlueprintStateValues;
                StateContext.ExportOwner = CDO;
                StateContext.BaselineExportOwner = ParentCDO;

                if (!ScanChangedPropertyInContainers(
                        StateContext,
                        Property,
                        CDO,
                        bCanCompareToParent ? ParentCDO : nullptr,
                        ArrayIndex))
                {
                    return false;
                }
            }
        }

        return true;
    }

    static bool ScanComponentTemplateProperties(
        UBlueprint* Blueprint,
        const FString& BlueprintPath,
        FJsonlWriter& ComponentPropertiesWriter,
        FJsonlWriter& StateValuesWriter,
        FScanCounts& Counts)
    {
        if (!Blueprint || !Blueprint->SimpleConstructionScript)
        {
            return true;
        }

        static constexpr uint64 SkipFlags =
            CPF_Transient | CPF_DuplicateTransient | CPF_NonPIEDuplicateTransient | CPF_Deprecated;

        for (USCS_Node* SCSNode : Blueprint->SimpleConstructionScript->GetAllNodes())
        {
            if (!SCSNode || !SCSNode->ComponentTemplate || !SCSNode->ComponentClass)
            {
                continue;
            }

            UObject* Template = SCSNode->ComponentTemplate;
            UObject* ClassDefault = SCSNode->ComponentClass->GetDefaultObject();
            if (!ClassDefault)
            {
                continue;
            }

            for (TFieldIterator<FProperty> It(SCSNode->ComponentClass, EFieldIterationFlags::IncludeSuper); It; ++It)
            {
                FProperty* Property = *It;
                if (!Property || Property->HasAnyPropertyFlags(SkipFlags))
                {
                    continue;
                }

                for (int32 ArrayIndex = 0; ArrayIndex < Property->ArrayDim; ++ArrayIndex)
                {
                    if (Property->Identical_InContainer(
                            Template, ClassDefault, ArrayIndex, PPF_None))
                    {
                        continue;
                    }

                    const FString Value = ExportPropertyTextInContainer(
                        Property, Template, Template, ArrayIndex, 65536);
                    const FString DefaultValue = ExportPropertyTextInContainer(
                        Property, ClassDefault, ClassDefault, ArrayIndex, 65536);
                    UObject* ObjectValue = GetObjectPropertyValueInContainer(
                        Property, Template, ArrayIndex);

                    const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
                    Json->SetStringField(TEXT("blueprint_path"), BlueprintPath);
                    Json->SetStringField(
                        TEXT("component_name"),
                        SCSNode->GetVariableName().ToString());
                    Json->SetStringField(
                        TEXT("component_class"),
                        SCSNode->ComponentClass->GetPathName());
                    Json->SetStringField(
                        TEXT("template_path"),
                        Template->GetPathName());
                    Json->SetStringField(TEXT("property_name"), Property->GetName());
                    Json->SetStringField(
                        TEXT("declaring_class"),
                        Property->GetOwnerClass()
                            ? Property->GetOwnerClass()->GetPathName()
                            : TEXT(""));
                    Json->SetNumberField(TEXT("array_index"), ArrayIndex);
                    Json->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
                    Json->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
                    Json->SetStringField(TEXT("value"), Value);
                    Json->SetStringField(TEXT("class_default_value"), DefaultValue);
                    Json->SetStringField(
                        TEXT("referenced_object_path"),
                        ObjectValue ? ObjectValue->GetPathName() : TEXT(""));
                    Json->SetStringField(
                        TEXT("referenced_object_class"),
                        ObjectValue ? ObjectValue->GetClass()->GetPathName() : TEXT(""));
                    Json->SetNumberField(
                        TEXT("property_flags"),
                        static_cast<double>(Property->GetPropertyFlags()));

                    if (!ComponentPropertiesWriter.Write(Json))
                    {
                        return false;
                    }
                    ++Counts.BlueprintComponentProperties;

                    FChangedValueScanContext StateContext;
                    StateContext.BlueprintPath = BlueprintPath;
                    StateContext.OwnerKind = TEXT("component_template");
                    StateContext.OwnerId = Template->GetPathName();
                    StateContext.OwnerName = SCSNode->GetVariableName().ToString();
                    StateContext.OwnerClass = SCSNode->ComponentClass->GetPathName();
                    StateContext.BaselineClass = SCSNode->ComponentClass->GetPathName();
                    StateContext.Writer = &StateValuesWriter;
                    StateContext.Counter = &Counts.BlueprintStateValues;
                    StateContext.ExportOwner = Template;
                    StateContext.BaselineExportOwner = ClassDefault;

                    if (!ScanChangedPropertyInContainers(
                            StateContext,
                            Property,
                            Template,
                            ClassDefault,
                            ArrayIndex))
                    {
                        return false;
                    }
                }
            }
        }

        return true;
    }


    static bool WriteTimelineCurveKeys(
        UObject* CurveObject,
        const FString& BlueprintPath,
        const FString& TimelinePath,
        const FString& TimelineName,
        int32 TrackIndex,
        const FString& TrackType,
        const FString& TrackName,
        FJsonlWriter& TimelineKeysWriter,
        FScanCounts& Counts)
    {
        UCurveBase* Curve = Cast<UCurveBase>(CurveObject);
        if (!Curve)
        {
            return true;
        }

        // Timeline templates use UCurveFloat/UCurveVector/UCurveLinearColor,
        // all of which expose FRichCurve channels through UCurveBase::GetCurves.
        // Avoid assuming arbitrary UCurveBase subclasses also use FRichCurve.
        const FString CurveClassName = Curve->GetClass()->GetName();
        if (CurveClassName != TEXT("CurveFloat") &&
            CurveClassName != TEXT("CurveVector") &&
            CurveClassName != TEXT("CurveLinearColor"))
        {
            return true;
        }

        const UCurveBase* ConstCurve = Curve;
        TArray<FRichCurveEditInfoConst> Curves;
        ConstCurve->GetCurves(Curves);
        for (int32 ChannelIndex = 0; ChannelIndex < Curves.Num(); ++ChannelIndex)
        {
            const FRichCurveEditInfoConst& CurveInfo = Curves[ChannelIndex];
            if (!CurveInfo.CurveToEdit)
            {
                continue;
            }

            const FRichCurve* RichCurve =
                static_cast<const FRichCurve*>(CurveInfo.CurveToEdit);
            const TArray<FRichCurveKey>& Keys = RichCurve->GetConstRefOfKeys();

            for (int32 KeyIndex = 0; KeyIndex < Keys.Num(); ++KeyIndex)
            {
                const FRichCurveKey& Key = Keys[KeyIndex];

                const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
                Json->SetStringField(TEXT("blueprint_path"), BlueprintPath);
                Json->SetStringField(TEXT("timeline_path"), TimelinePath);
                Json->SetStringField(TEXT("timeline_name"), TimelineName);
                Json->SetNumberField(TEXT("track_index"), TrackIndex);
                Json->SetStringField(TEXT("track_type"), TrackType);
                Json->SetStringField(TEXT("track_name"), TrackName);
                Json->SetStringField(
                    TEXT("curve_path"),
                    CurveObject ? CurveObject->GetPathName() : TEXT(""));
                Json->SetStringField(
                    TEXT("curve_class"),
                    CurveObject ? CurveObject->GetClass()->GetPathName() : TEXT(""));
                Json->SetNumberField(TEXT("channel_index"), ChannelIndex);
                Json->SetStringField(TEXT("channel_name"), CurveInfo.CurveName.ToString());
                Json->SetNumberField(TEXT("key_index"), KeyIndex);
                Json->SetNumberField(TEXT("time"), Key.Time);
                Json->SetNumberField(TEXT("value"), Key.Value);
                Json->SetNumberField(
                    TEXT("interp_mode"),
                    static_cast<int32>(Key.InterpMode));
                Json->SetNumberField(
                    TEXT("tangent_mode"),
                    static_cast<int32>(Key.TangentMode));
                Json->SetNumberField(
                    TEXT("tangent_weight_mode"),
                    static_cast<int32>(Key.TangentWeightMode));
                Json->SetNumberField(TEXT("arrive_tangent"), Key.ArriveTangent);
                Json->SetNumberField(TEXT("leave_tangent"), Key.LeaveTangent);
                Json->SetNumberField(TEXT("arrive_tangent_weight"), Key.ArriveTangentWeight);
                Json->SetNumberField(TEXT("leave_tangent_weight"), Key.LeaveTangentWeight);

                if (!TimelineKeysWriter.Write(Json))
                {
                    return false;
                }
                ++Counts.BlueprintTimelineKeys;
            }
        }

        return true;
    }

    static bool WriteTimelineTrackArray(
        UObject* Timeline,
        const FString& BlueprintPath,
        const FString& TimelinePath,
        const FString& TimelineName,
        const FName ArrayPropertyName,
        const FString& TrackType,
        FJsonlWriter& TimelineTracksWriter,
        FJsonlWriter& TimelineKeysWriter,
        FScanCounts& Counts)
    {
        if (!Timeline)
        {
            return true;
        }

        FArrayProperty* ArrayProperty = CastField<FArrayProperty>(
            Timeline->GetClass()->FindPropertyByName(ArrayPropertyName));
        if (!ArrayProperty)
        {
            return true;
        }

        FStructProperty* InnerStructProperty = CastField<FStructProperty>(ArrayProperty->Inner);
        if (!InnerStructProperty || !InnerStructProperty->Struct)
        {
            return true;
        }

        const void* ArrayValue = ArrayProperty->ContainerPtrToValuePtr<void>(Timeline);
        if (!ArrayValue)
        {
            return true;
        }

        FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
        for (int32 TrackIndex = 0; TrackIndex < Helper.Num(); ++TrackIndex)
        {
            const void* TrackValue = Helper.GetRawPtr(TrackIndex);
            UStruct* TrackStruct = InnerStructProperty->Struct;

            const FString TrackName = ExportStructFieldText(
                TrackStruct, TrackValue, TEXT("TrackName"), Timeline);
            const FString PropertyName = ExportStructFieldText(
                TrackStruct, TrackValue, TEXT("PropertyName"), Timeline);
            const FString FunctionName = ExportStructFieldText(
                TrackStruct, TrackValue, TEXT("FunctionName"), Timeline);
            const FString bExternalCurve = ExportStructFieldText(
                TrackStruct, TrackValue, TEXT("bIsExternalCurve"), Timeline);

            UObject* Curve = nullptr;
            static const FName CurveFields[] =
            {
                TEXT("CurveFloat"),
                TEXT("CurveVector"),
                TEXT("CurveLinearColor"),
                TEXT("CurveKeys")
            };
            for (const FName CurveField : CurveFields)
            {
                Curve = GetStructObjectField(TrackStruct, TrackValue, CurveField);
                if (Curve)
                {
                    break;
                }
            }

            FString RawValue;
            InnerStructProperty->ExportTextItem_Direct(
                RawValue, TrackValue, nullptr, Timeline, PPF_None, nullptr);
            if (RawValue.Len() > 32768)
            {
                RawValue = RawValue.Left(32768);
            }

            const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
            Json->SetStringField(TEXT("blueprint_path"), BlueprintPath);
            Json->SetStringField(TEXT("timeline_path"), TimelinePath);
            Json->SetStringField(TEXT("timeline_name"), TimelineName);
            Json->SetNumberField(TEXT("track_index"), TrackIndex);
            Json->SetStringField(TEXT("track_type"), TrackType);
            Json->SetStringField(TEXT("track_struct"), TrackStruct->GetPathName());
            Json->SetStringField(TEXT("track_name"), TrackName);
            Json->SetStringField(TEXT("property_name"), PropertyName);
            Json->SetStringField(TEXT("function_name"), FunctionName);
            Json->SetStringField(TEXT("external_curve"), bExternalCurve);
            Json->SetStringField(
                TEXT("curve_path"),
                Curve ? Curve->GetPathName() : TEXT(""));
            Json->SetStringField(
                TEXT("curve_class"),
                Curve ? Curve->GetClass()->GetPathName() : TEXT(""));
            Json->SetStringField(TEXT("raw_value"), RawValue);

            if (!TimelineTracksWriter.Write(Json))
            {
                return false;
            }
            ++Counts.BlueprintTimelineTracks;

            if (Curve &&
                !WriteTimelineCurveKeys(
                    Curve,
                    BlueprintPath,
                    TimelinePath,
                    TimelineName,
                    TrackIndex,
                    TrackType,
                    TrackName,
                    TimelineKeysWriter,
                    Counts))
            {
                return false;
            }
        }

        return true;
    }

    static bool ScanBlueprintTimelines(
        UBlueprint* Blueprint,
        const FString& BlueprintPath,
        FJsonlWriter& TimelinesWriter,
        FJsonlWriter& TimelineTracksWriter,
        FJsonlWriter& TimelineKeysWriter,
        FScanCounts& Counts)
    {
        if (!Blueprint)
        {
            return true;
        }

        TArray<UObject*> Timelines;
        GetReflectedObjectArray(Blueprint, TEXT("Timelines"), Timelines);
        for (UObject* Timeline : Timelines)
        {
            if (!Timeline)
            {
                continue;
            }

            const FString TimelinePath = Timeline->GetPathName();
            FString TimelineName = Timeline->GetName();
            TimelineName.RemoveFromEnd(TEXT("_Template"));

            const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
            Json->SetStringField(TEXT("blueprint_path"), BlueprintPath);
            Json->SetStringField(TEXT("timeline_path"), TimelinePath);
            Json->SetStringField(TEXT("timeline_name"), TimelineName);
            Json->SetStringField(TEXT("timeline_class"), Timeline->GetClass()->GetPathName());
            Json->SetStringField(TEXT("guid"), ExportReflectedPropertyText(Timeline, TEXT("TimelineGuid")));
            Json->SetStringField(TEXT("length"), ExportReflectedPropertyText(Timeline, TEXT("TimelineLength")));
            Json->SetStringField(TEXT("length_mode"), ExportReflectedPropertyText(Timeline, TEXT("LengthMode")));
            Json->SetStringField(TEXT("auto_play"), ExportReflectedPropertyText(Timeline, TEXT("bAutoPlay")));
            Json->SetStringField(TEXT("loop"), ExportReflectedPropertyText(Timeline, TEXT("bLoop")));
            Json->SetStringField(TEXT("replicated"), ExportReflectedPropertyText(Timeline, TEXT("bReplicated")));
            Json->SetStringField(TEXT("ignore_time_dilation"), ExportReflectedPropertyText(Timeline, TEXT("bIgnoreTimeDilation")));
            Json->SetStringField(TEXT("tick_group"), ExportReflectedPropertyText(Timeline, TEXT("TimelineTickGroup")));
            Json->SetStringField(TEXT("update_function"), ExportReflectedPropertyText(Timeline, TEXT("UpdateFunctionName")));
            Json->SetStringField(TEXT("finished_function"), ExportReflectedPropertyText(Timeline, TEXT("FinishedFunctionName")));
            Json->SetStringField(TEXT("direction_property"), ExportReflectedPropertyText(Timeline, TEXT("DirectionPropertyName")));
            Json->SetStringField(TEXT("variable_name"), ExportReflectedPropertyText(Timeline, TEXT("VariableName")));

            if (!TimelinesWriter.Write(Json))
            {
                return false;
            }
            ++Counts.BlueprintTimelines;

            if (!WriteTimelineTrackArray(
                    Timeline, BlueprintPath, TimelinePath, TimelineName,
                    TEXT("FloatTracks"), TEXT("float"), TimelineTracksWriter, TimelineKeysWriter, Counts) ||
                !WriteTimelineTrackArray(
                    Timeline, BlueprintPath, TimelinePath, TimelineName,
                    TEXT("VectorTracks"), TEXT("vector"), TimelineTracksWriter, TimelineKeysWriter, Counts) ||
                !WriteTimelineTrackArray(
                    Timeline, BlueprintPath, TimelinePath, TimelineName,
                    TEXT("LinearColorTracks"), TEXT("linear_color"), TimelineTracksWriter, TimelineKeysWriter, Counts) ||
                !WriteTimelineTrackArray(
                    Timeline, BlueprintPath, TimelinePath, TimelineName,
                    TEXT("EventTracks"), TEXT("event"), TimelineTracksWriter, TimelineKeysWriter, Counts))
            {
                return false;
            }
        }

        return true;
    }

    static TSharedRef<FJsonObject> SelectedObjectPropertiesToJson(
        UObject* Object,
        const TArray<FName>& PropertyNames)
    {
        const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
        if (!Object)
        {
            return Json;
        }

        for (const FName PropertyName : PropertyNames)
        {
            FProperty* Property = Object->GetClass()->FindPropertyByName(PropertyName);
            if (!Property || !IsCapturableProperty(Property))
            {
                continue;
            }
            Json->SetStringField(
                PropertyName.ToString(),
                ExportPropertyTextInContainer(Property, Object, Object, 0, 16384));
        }
        return Json;
    }

    static TSharedRef<FJsonObject> SlotPropertiesToJson(UObject* Slot)
    {
        const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
        if (!Slot)
        {
            return Json;
        }

        int32 Written = 0;
        for (UClass* Class = Slot->GetClass();
             Class && Class != UObject::StaticClass();
             Class = Class->GetSuperClass())
        {
            for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
            {
                FProperty* Property = *It;
                if (!IsCapturableProperty(Property) ||
                    Property->GetFName() == TEXT("Content") ||
                    Property->GetFName() == TEXT("Parent"))
                {
                    continue;
                }

                Json->SetStringField(
                    Property->GetName(),
                    ExportPropertyTextInContainer(Property, Slot, Slot, 0, 4096));
                if (++Written >= 64)
                {
                    return Json;
                }
            }

            if (Class->GetFName() == TEXT("PanelSlot"))
            {
                break;
            }
        }
        return Json;
    }


    static bool ScanObjectOverridesAgainstClassDefault(
        UObject* Object,
        const FString& BlueprintPath,
        const FString& OwnerKind,
        const FString& OwnerName,
        const TSet<FName>& SkipPropertyNames,
        FJsonlWriter& WidgetPropertiesWriter,
        FScanCounts& Counts)
    {
        if (!Object || !Object->GetClass())
        {
            return true;
        }

        UObject* ClassDefault = Object->GetClass()->GetDefaultObject();
        if (!ClassDefault)
        {
            return true;
        }

        static constexpr uint64 SkipFlags =
            CPF_Transient | CPF_DuplicateTransient | CPF_NonPIEDuplicateTransient | CPF_Deprecated;

        FChangedValueScanContext StateContext;
        StateContext.BlueprintPath = BlueprintPath;
        StateContext.OwnerKind = OwnerKind;
        StateContext.OwnerId = Object->GetPathName();
        StateContext.OwnerName = OwnerName;
        StateContext.OwnerClass = Object->GetClass()->GetPathName();
        StateContext.BaselineClass = Object->GetClass()->GetPathName();
        StateContext.Writer = &WidgetPropertiesWriter;
        StateContext.Counter = &Counts.BlueprintWidgetProperties;
        StateContext.ExportOwner = Object;
        StateContext.BaselineExportOwner = ClassDefault;

        for (TFieldIterator<FProperty> It(
                 Object->GetClass(),
                 EFieldIterationFlags::IncludeSuper);
             It;
             ++It)
        {
            FProperty* Property = *It;
            if (!Property ||
                Property->HasAnyPropertyFlags(SkipFlags) ||
                SkipPropertyNames.Contains(Property->GetFName()))
            {
                continue;
            }

            for (int32 ArrayIndex = 0; ArrayIndex < Property->ArrayDim; ++ArrayIndex)
            {
                if (Property->Identical_InContainer(
                        Object,
                        ClassDefault,
                        ArrayIndex,
                        PPF_None))
                {
                    continue;
                }

                if (!ScanChangedPropertyInContainers(
                        StateContext,
                        Property,
                        Object,
                        ClassDefault,
                        ArrayIndex))
                {
                    return false;
                }
            }
        }

        return true;
    }

    static bool WriteWidgetBindings(
        UBlueprint* Blueprint,
        const FString& BlueprintPath,
        FJsonlWriter& WidgetBindingsWriter,
        FScanCounts& Counts)
    {
        if (!Blueprint)
        {
            return true;
        }

        FArrayProperty* ArrayProperty = CastField<FArrayProperty>(
            Blueprint->GetClass()->FindPropertyByName(TEXT("Bindings")));
        if (!ArrayProperty)
        {
            return true;
        }

        FStructProperty* InnerStructProperty = CastField<FStructProperty>(ArrayProperty->Inner);
        if (!InnerStructProperty || !InnerStructProperty->Struct)
        {
            return true;
        }

        const void* ArrayValue = ArrayProperty->ContainerPtrToValuePtr<void>(Blueprint);
        if (!ArrayValue)
        {
            return true;
        }

        FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
        for (int32 BindingIndex = 0; BindingIndex < Helper.Num(); ++BindingIndex)
        {
            const void* BindingValue = Helper.GetRawPtr(BindingIndex);
            UStruct* BindingStruct = InnerStructProperty->Struct;

            const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
            Json->SetStringField(TEXT("blueprint_path"), BlueprintPath);
            Json->SetNumberField(TEXT("binding_index"), BindingIndex);
            Json->SetStringField(TEXT("binding_struct"), BindingStruct->GetPathName());
            Json->SetStringField(TEXT("object_name"),
                ExportStructFieldText(BindingStruct, BindingValue, TEXT("ObjectName"), Blueprint));
            Json->SetStringField(TEXT("property_name"),
                ExportStructFieldText(BindingStruct, BindingValue, TEXT("PropertyName"), Blueprint));
            Json->SetStringField(TEXT("function_name"),
                ExportStructFieldText(BindingStruct, BindingValue, TEXT("FunctionName"), Blueprint));
            Json->SetStringField(TEXT("source_property"),
                ExportStructFieldText(BindingStruct, BindingValue, TEXT("SourceProperty"), Blueprint));
            Json->SetStringField(TEXT("source_path"),
                ExportStructFieldText(BindingStruct, BindingValue, TEXT("SourcePath"), Blueprint));
            Json->SetStringField(TEXT("kind"),
                ExportStructFieldText(BindingStruct, BindingValue, TEXT("Kind"), Blueprint));
            Json->SetStringField(TEXT("member_guid"),
                ExportStructFieldText(BindingStruct, BindingValue, TEXT("MemberGuid"), Blueprint));

            FString RawValue;
            InnerStructProperty->ExportTextItem_Direct(
                RawValue, BindingValue, nullptr, Blueprint, PPF_None, nullptr);
            if (RawValue.Len() > 32768)
            {
                RawValue = RawValue.Left(32768);
            }
            Json->SetStringField(TEXT("raw_value"), RawValue);

            if (!WidgetBindingsWriter.Write(Json))
            {
                return false;
            }
            ++Counts.BlueprintWidgetBindings;
        }

        return true;
    }


    static bool WriteWidgetAnimationBindings(
        UObject* Animation,
        const FString& BlueprintPath,
        FJsonlWriter& WidgetAnimationBindingsWriter,
        FScanCounts& Counts)
    {
        if (!Animation)
        {
            return true;
        }

        FArrayProperty* ArrayProperty = CastField<FArrayProperty>(
            Animation->GetClass()->FindPropertyByName(TEXT("AnimationBindings")));
        FStructProperty* InnerStruct = ArrayProperty
            ? CastField<FStructProperty>(ArrayProperty->Inner)
            : nullptr;
        if (!ArrayProperty || !InnerStruct || !InnerStruct->Struct)
        {
            return true;
        }

        const void* ArrayValue = ArrayProperty->ContainerPtrToValuePtr<void>(Animation);
        if (!ArrayValue)
        {
            return true;
        }

        FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
        for (int32 BindingIndex = 0; BindingIndex < Helper.Num(); ++BindingIndex)
        {
            const void* BindingValue = Helper.GetRawPtr(BindingIndex);
            UStruct* BindingStruct = InnerStruct->Struct;

            const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
            Json->SetStringField(TEXT("blueprint_path"), BlueprintPath);
            Json->SetStringField(TEXT("animation_path"), Animation->GetPathName());
            Json->SetStringField(TEXT("animation_name"), Animation->GetName());
            Json->SetNumberField(TEXT("binding_index"), BindingIndex);
            Json->SetStringField(TEXT("binding_struct"), BindingStruct->GetPathName());
            Json->SetStringField(
                TEXT("widget_name"),
                ExportStructFieldText(
                    BindingStruct,
                    BindingValue,
                    TEXT("WidgetName"),
                    Animation));
            Json->SetStringField(
                TEXT("slot_widget_name"),
                ExportStructFieldText(
                    BindingStruct,
                    BindingValue,
                    TEXT("SlotWidgetName"),
                    Animation));
            Json->SetStringField(
                TEXT("animation_guid"),
                ExportStructFieldText(
                    BindingStruct,
                    BindingValue,
                    TEXT("AnimationGuid"),
                    Animation));
            Json->SetStringField(
                TEXT("is_root_widget"),
                ExportStructFieldText(
                    BindingStruct,
                    BindingValue,
                    TEXT("bIsRootWidget"),
                    Animation));
            Json->SetStringField(
                TEXT("dynamic_binding"),
                ExportStructFieldText(
                    BindingStruct,
                    BindingValue,
                    TEXT("DynamicBinding"),
                    Animation,
                    16384));

            if (!WidgetAnimationBindingsWriter.Write(Json))
            {
                return false;
            }
            ++Counts.BlueprintWidgetAnimationBindings;
        }

        return true;
    }

    static bool ScanBlueprintWidgets(
        UBlueprint* Blueprint,
        const FString& BlueprintPath,
        FJsonlWriter& WidgetsWriter,
        FJsonlWriter& WidgetPropertiesWriter,
        FJsonlWriter& WidgetBindingsWriter,
        FJsonlWriter& WidgetAnimationsWriter,
        FJsonlWriter& WidgetAnimationBindingsWriter,
        FScanCounts& Counts)
    {
        if (!Blueprint)
        {
            return true;
        }

        UObject* WidgetTree = GetReflectedObjectProperty(Blueprint, TEXT("WidgetTree"));
        if (WidgetTree)
        {
            TArray<UObject*> OwnedObjects;
            GetObjectsWithOuter(
                WidgetTree,
                OwnedObjects,
                EGetObjectsFlags::IncludeNestedObjects);

            static const TArray<FName> WidgetPropertyNames =
            {
                TEXT("bIsVariable"),
                TEXT("Visibility"),
                TEXT("bIsEnabled"),
                TEXT("RenderOpacity"),
                TEXT("RenderTransform"),
                TEXT("RenderTransformPivot"),
                TEXT("ToolTipText"),
                TEXT("bHiddenInDesigner"),
                TEXT("bLockedInDesigner"),
                TEXT("bExpandedInDesigner")
            };

            for (UObject* Object : OwnedObjects)
            {
                if (!Object ||
                    !ClassIsOrDerivedFromName(Object->GetClass(), TEXT("Widget")))
                {
                    continue;
                }

                UObject* Slot = GetReflectedObjectProperty(Object, TEXT("Slot"));
                UObject* ParentWidget = Slot
                    ? GetReflectedObjectProperty(Slot, TEXT("Parent"))
                    : nullptr;

                const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
                Json->SetStringField(TEXT("blueprint_path"), BlueprintPath);
                Json->SetStringField(TEXT("widget_tree"), WidgetTree->GetPathName());
                Json->SetStringField(TEXT("widget_path"), Object->GetPathName());
                Json->SetStringField(TEXT("widget_name"), Object->GetName());
                Json->SetStringField(TEXT("widget_class"), Object->GetClass()->GetPathName());
                Json->SetStringField(
                    TEXT("parent_widget_path"),
                    ParentWidget ? ParentWidget->GetPathName() : TEXT(""));
                Json->SetStringField(
                    TEXT("parent_widget_name"),
                    ParentWidget ? ParentWidget->GetName() : TEXT(""));
                Json->SetStringField(
                    TEXT("slot_path"),
                    Slot ? Slot->GetPathName() : TEXT(""));
                Json->SetStringField(
                    TEXT("slot_class"),
                    Slot ? Slot->GetClass()->GetPathName() : TEXT(""));
                Json->SetObjectField(
                    TEXT("properties"),
                    SelectedObjectPropertiesToJson(Object, WidgetPropertyNames));
                Json->SetObjectField(
                    TEXT("slot_properties"),
                    SlotPropertiesToJson(Slot));

                if (!WidgetsWriter.Write(Json))
                {
                    return false;
                }
                ++Counts.BlueprintWidgets;

                const TSet<FName> WidgetSkipProperties =
                {
                    TEXT("Slot")
                };
                if (!ScanObjectOverridesAgainstClassDefault(
                        Object,
                        BlueprintPath,
                        TEXT("widget"),
                        Object->GetName(),
                        WidgetSkipProperties,
                        WidgetPropertiesWriter,
                        Counts))
                {
                    return false;
                }

                if (Slot)
                {
                    const TSet<FName> SlotSkipProperties =
                    {
                        TEXT("Parent"),
                        TEXT("Content")
                    };
                    if (!ScanObjectOverridesAgainstClassDefault(
                            Slot,
                            BlueprintPath,
                            TEXT("widget_slot"),
                            Object->GetName(),
                            SlotSkipProperties,
                            WidgetPropertiesWriter,
                            Counts))
                    {
                        return false;
                    }
                }
            }
        }

        if (!WriteWidgetBindings(
                Blueprint,
                BlueprintPath,
                WidgetBindingsWriter,
                Counts))
        {
            return false;
        }

        TArray<UObject*> Animations;
        GetReflectedObjectArray(Blueprint, TEXT("Animations"), Animations);
        for (int32 AnimationIndex = 0; AnimationIndex < Animations.Num(); ++AnimationIndex)
        {
            UObject* Animation = Animations[AnimationIndex];
            if (!Animation)
            {
                continue;
            }

            UObject* MovieScene = GetReflectedObjectProperty(Animation, TEXT("MovieScene"));
            const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
            Json->SetStringField(TEXT("blueprint_path"), BlueprintPath);
            Json->SetNumberField(TEXT("animation_index"), AnimationIndex);
            Json->SetStringField(TEXT("animation_path"), Animation->GetPathName());
            Json->SetStringField(TEXT("animation_name"), Animation->GetName());
            Json->SetStringField(TEXT("animation_class"), Animation->GetClass()->GetPathName());
            Json->SetStringField(
                TEXT("display_label"),
                ExportReflectedPropertyText(Animation, TEXT("DisplayLabel")));
            Json->SetStringField(
                TEXT("movie_scene"),
                MovieScene ? MovieScene->GetPathName() : TEXT(""));
            Json->SetStringField(
                TEXT("animation_bindings"),
                ExportReflectedPropertyText(Animation, TEXT("AnimationBindings")));

            if (!WidgetAnimationsWriter.Write(Json))
            {
                return false;
            }
            ++Counts.BlueprintWidgetAnimations;

            if (!WriteWidgetAnimationBindings(
                    Animation,
                    BlueprintPath,
                    WidgetAnimationBindingsWriter,
                    Counts))
            {
                return false;
            }
        }

        return true;
    }

    static bool ScanBlueprint(
        UBlueprint* Blueprint,
        const FString& ObjectPath,
        FJsonlWriter& BlueprintsWriter,
        FJsonlWriter& GraphsWriter,
        FJsonlWriter& NodesWriter,
        FJsonlWriter& PinsWriter,
        FJsonlWriter& PropertiesWriter,
        FJsonlWriter& ReferencesWriter,
        FJsonlWriter& BindingsWriter,
        FJsonlWriter& InterfacesWriter,
        FJsonlWriter& DefaultsWriter,
        FJsonlWriter& ComponentPropertiesWriter,
        FJsonlWriter& StateValuesWriter,
        FJsonlWriter& TimelinesWriter,
        FJsonlWriter& TimelineTracksWriter,
        FJsonlWriter& TimelineKeysWriter,
        FJsonlWriter& WidgetsWriter,
        FJsonlWriter& WidgetPropertiesWriter,
        FJsonlWriter& WidgetBindingsWriter,
        FJsonlWriter& WidgetAnimationsWriter,
        FJsonlWriter& WidgetAnimationBindingsWriter,
        FJsonlWriter& RigVMObjectsWriter,
        FJsonlWriter& RigVMPinsWriter,
        FJsonlWriter& RigVMLinksWriter,
        FJsonlWriter& RigVMPropertiesWriter,
        FJsonlWriter& RigVMReferencesWriter,
        FJsonlWriter& EdgesWriter,
        bool bIncludeRawRigVMProperties,
        FScanCounts& Counts)
    {
        const TSharedRef<FJsonObject> BlueprintJson = MakeShared<FJsonObject>();
        BlueprintJson->SetStringField(TEXT("object_path"), ObjectPath);
        BlueprintJson->SetStringField(TEXT("name"), Blueprint->GetName());
        BlueprintJson->SetStringField(TEXT("class"), Blueprint->GetClass()->GetPathName());
        BlueprintJson->SetStringField(TEXT("parent_class"), Blueprint->ParentClass ? Blueprint->ParentClass->GetPathName() : TEXT(""));
        BlueprintJson->SetStringField(TEXT("generated_class"), Blueprint->GeneratedClass ? Blueprint->GeneratedClass->GetPathName() : TEXT(""));
        BlueprintJson->SetNumberField(TEXT("blueprint_type"), static_cast<int32>(Blueprint->BlueprintType));
        BlueprintJson->SetNumberField(TEXT("status"), static_cast<int32>(Blueprint->Status));

        TArray<TSharedPtr<FJsonValue>> VariablesJson;
        for (const FBPVariableDescription& Variable : Blueprint->NewVariables)
        {
            const TSharedRef<FJsonObject> VariableJson = MakeShared<FJsonObject>();
            VariableJson->SetStringField(TEXT("name"), Variable.VarName.ToString());
            VariableJson->SetStringField(TEXT("guid"), Variable.VarGuid.ToString(EGuidFormats::DigitsWithHyphensLower));
            VariableJson->SetStringField(TEXT("category"), Variable.Category.ToString());
            VariableJson->SetStringField(TEXT("default_value"), Variable.DefaultValue);
            VariableJson->SetNumberField(TEXT("property_flags"), static_cast<double>(Variable.PropertyFlags));
            VariableJson->SetObjectField(TEXT("type"), PinTypeToJson(Variable.VarType));
            VariablesJson.Add(MakeShared<FJsonValueObject>(VariableJson));
            ++Counts.BlueprintVariables;
        }
        BlueprintJson->SetArrayField(TEXT("variables"), VariablesJson);

        TArray<TSharedPtr<FJsonValue>> ComponentsJson;
        if (Blueprint->SimpleConstructionScript)
        {
            for (USCS_Node* SCSNode : Blueprint->SimpleConstructionScript->GetAllNodes())
            {
                if (!SCSNode)
                {
                    continue;
                }
                const TSharedRef<FJsonObject> ComponentJson = MakeShared<FJsonObject>();
                ComponentJson->SetStringField(TEXT("variable_name"), SCSNode->GetVariableName().ToString());
                ComponentJson->SetStringField(TEXT("component_class"), SCSNode->ComponentClass ? SCSNode->ComponentClass->GetPathName() : TEXT(""));
                ComponentJson->SetStringField(TEXT("template"), SCSNode->ComponentTemplate ? SCSNode->ComponentTemplate->GetPathName() : TEXT(""));
                ComponentJson->SetStringField(TEXT("parent_component_or_variable"), SCSNode->ParentComponentOrVariableName.ToString());
                ComponentJson->SetStringField(TEXT("parent_owner_class"), SCSNode->ParentComponentOwnerClassName.ToString());
                ComponentJson->SetStringField(TEXT("attach_to"), SCSNode->AttachToName.ToString());
                ComponentJson->SetStringField(TEXT("guid"), SCSNode->VariableGuid.ToString(EGuidFormats::DigitsWithHyphensLower));
                ComponentJson->SetBoolField(TEXT("is_root"), SCSNode->IsRootNode());
                ComponentsJson.Add(MakeShared<FJsonValueObject>(ComponentJson));
                ++Counts.BlueprintComponents;
            }
        }
        BlueprintJson->SetArrayField(TEXT("components"), ComponentsJson);

        TArray<TSharedPtr<FJsonValue>> InterfacesJson;
        for (const FBPInterfaceDescription& InterfaceDescription : Blueprint->ImplementedInterfaces)
        {
            UClass* InterfaceClass = InterfaceDescription.Interface.Get();
            if (!InterfaceClass)
            {
                continue;
            }

            const FString InterfacePath = InterfaceClass->GetPathName();
            InterfacesJson.Add(MakeShared<FJsonValueString>(InterfacePath));

            const TSharedRef<FJsonObject> InterfaceJson = MakeShared<FJsonObject>();
            InterfaceJson->SetStringField(TEXT("blueprint_path"), ObjectPath);
            InterfaceJson->SetStringField(TEXT("interface_class"), InterfacePath);
            InterfaceJson->SetStringField(TEXT("interface_name"), InterfaceClass->GetName());

            TArray<TSharedPtr<FJsonValue>> InterfaceGraphsJson;
            for (const TObjectPtr<UEdGraph>& InterfaceGraphPtr : InterfaceDescription.Graphs)
            {
                UEdGraph* InterfaceGraph = InterfaceGraphPtr.Get();
                if (InterfaceGraph)
                {
                    InterfaceGraphsJson.Add(MakeShared<FJsonValueString>(InterfaceGraph->GetPathName()));
                }
            }
            InterfaceJson->SetArrayField(TEXT("graphs"), InterfaceGraphsJson);

            if (!InterfacesWriter.Write(InterfaceJson))
            {
                return false;
            }
            ++Counts.BlueprintInterfaces;
        }
        BlueprintJson->SetArrayField(TEXT("implemented_interfaces"), InterfacesJson);

        TArray<UEdGraph*> Graphs;
        Blueprint->GetAllGraphs(Graphs);

        // GetAllGraphs can return the same nested graph more than once (seen in
        // Control Rig assets in Content Examples). Deduplicate by full object
        // path before assigning IDs or writing JSONL rows.
        TArray<UEdGraph*> UniqueGraphs;
        TSet<FString> SeenGraphPaths;
        UniqueGraphs.Reserve(Graphs.Num());
        for (UEdGraph* Graph : Graphs)
        {
            if (!Graph)
            {
                continue;
            }
            const FString GraphPath = Graph->GetPathName();
            if (SeenGraphPaths.Contains(GraphPath))
            {
                continue;
            }
            SeenGraphPaths.Add(GraphPath);
            UniqueGraphs.Add(Graph);
        }
        BlueprintJson->SetNumberField(TEXT("graph_count"), UniqueGraphs.Num());

        if (!BlueprintsWriter.Write(BlueprintJson))
        {
            return false;
        }
        ++Counts.Blueprints;

        if (!ScanBlueprintDefaults(
                Blueprint,
                ObjectPath,
                DefaultsWriter,
                StateValuesWriter,
                Counts) ||
            !ScanComponentTemplateProperties(
                Blueprint,
                ObjectPath,
                ComponentPropertiesWriter,
                StateValuesWriter,
                Counts) ||
            !ScanBlueprintTimelines(
                Blueprint,
                ObjectPath,
                TimelinesWriter,
                TimelineTracksWriter,
                TimelineKeysWriter,
                Counts) ||
            !ScanBlueprintWidgets(
                Blueprint,
                ObjectPath,
                WidgetsWriter,
                WidgetPropertiesWriter,
                WidgetBindingsWriter,
                WidgetAnimationsWriter,
                WidgetAnimationBindingsWriter,
                Counts))
        {
            return false;
        }

        for (UEdGraph* Graph : UniqueGraphs)
        {
            if (!Graph)
            {
                continue;
            }
            ++Counts.BlueprintGraphs;

            const FString GraphId = MakeGraphId(ObjectPath, Graph);
            const FString GraphPath = Graph->GetPathName();
            const FString GraphKindValue = GraphKind(Blueprint, Graph);
            const FString GraphSystemValue = GraphSystem(Graph);

            const TSharedRef<FJsonObject> GraphJson = MakeShared<FJsonObject>();
            GraphJson->SetStringField(TEXT("graph_id"), GraphId);
            GraphJson->SetStringField(TEXT("blueprint_path"), ObjectPath);
            GraphJson->SetStringField(TEXT("graph_name"), Graph->GetName());
            GraphJson->SetStringField(TEXT("graph_path"), GraphPath);
            GraphJson->SetStringField(TEXT("graph_kind"), GraphKindValue);
            GraphJson->SetStringField(TEXT("graph_system"), GraphSystemValue);
            GraphJson->SetStringField(TEXT("graph_class"), Graph->GetClass()->GetPathName());
            GraphJson->SetStringField(TEXT("schema_class"), Graph->GetSchema() ? Graph->GetSchema()->GetClass()->GetPathName() : TEXT(""));

            TSet<FString> UniqueGraphNodeIds;
            for (int32 NodeIndex = 0; NodeIndex < Graph->Nodes.Num(); ++NodeIndex)
            {
                if (UEdGraphNode* CountNode = Graph->Nodes[NodeIndex])
                {
                    UniqueGraphNodeIds.Add(MakeNodeId(ObjectPath, Graph, CountNode, NodeIndex));
                }
            }
            GraphJson->SetNumberField(TEXT("node_count"), UniqueGraphNodeIds.Num());

            UObject* GraphOuter = Graph->GetOuter();
            GraphJson->SetStringField(TEXT("outer_path"), GraphOuter ? GraphOuter->GetPathName() : TEXT(""));
            GraphJson->SetStringField(TEXT("outer_class"), GraphOuter ? GraphOuter->GetClass()->GetPathName() : TEXT(""));
            if (UEdGraphNode* ParentNode = Cast<UEdGraphNode>(GraphOuter))
            {
                GraphJson->SetStringField(TEXT("parent_node_guid"), ParentNode->NodeGuid.ToString(EGuidFormats::DigitsWithHyphensLower));
                GraphJson->SetStringField(TEXT("parent_graph_path"), ParentNode->GetGraph() ? ParentNode->GetGraph()->GetPathName() : TEXT(""));
            }
            else
            {
                GraphJson->SetStringField(TEXT("parent_node_guid"), TEXT(""));
                GraphJson->SetStringField(TEXT("parent_graph_path"), TEXT(""));
            }

            if (!GraphsWriter.Write(GraphJson))
            {
                return false;
            }

            TMap<const UEdGraphNode*, FString> NodeIds;
            TMap<const UEdGraphPin*, FString> PinIds;
            TSet<FString> SeenNodeIds;
            TSet<FString> SeenPinIds;

            for (int32 NodeIndex = 0; NodeIndex < Graph->Nodes.Num(); ++NodeIndex)
            {
                UEdGraphNode* Node = Graph->Nodes[NodeIndex];
                if (!Node)
                {
                    continue;
                }

                const FString NodeId = MakeNodeId(ObjectPath, Graph, Node, NodeIndex);
                NodeIds.Add(Node, NodeId);
                if (SeenNodeIds.Contains(NodeId))
                {
                    continue;
                }
                SeenNodeIds.Add(NodeId);

                const TSharedRef<FJsonObject> NodeJson = MakeShared<FJsonObject>();
                NodeJson->SetStringField(TEXT("node_id"), NodeId);
                NodeJson->SetStringField(TEXT("blueprint_path"), ObjectPath);
                NodeJson->SetStringField(TEXT("graph_id"), GraphId);
                NodeJson->SetStringField(TEXT("graph_name"), Graph->GetName());
                NodeJson->SetStringField(TEXT("graph_path"), GraphPath);
                NodeJson->SetStringField(TEXT("graph_kind"), GraphKindValue);
                NodeJson->SetStringField(TEXT("graph_system"), GraphSystemValue);
                NodeJson->SetStringField(TEXT("graph_class"), Graph->GetClass()->GetPathName());
                NodeJson->SetStringField(TEXT("schema_class"), Graph->GetSchema() ? Graph->GetSchema()->GetClass()->GetPathName() : TEXT(""));
                NodeJson->SetStringField(TEXT("node_class"), Node->GetClass()->GetPathName());
                NodeJson->SetStringField(TEXT("title"), Node->GetNodeTitle(ENodeTitleType::FullTitle).ToString());
                NodeJson->SetStringField(TEXT("comment"), Node->NodeComment);
                NodeJson->SetNumberField(TEXT("x"), Node->NodePosX);
                NodeJson->SetNumberField(TEXT("y"), Node->NodePosY);

                FString Operation;
                FString Symbol;
                FString Owner;
                const TSharedRef<FJsonObject> Semantic = BuildNodeSemantic(Blueprint, Node, Operation, Symbol, Owner);
                NodeJson->SetStringField(TEXT("operation"), Operation);
                NodeJson->SetStringField(TEXT("symbol"), Symbol);
                NodeJson->SetStringField(TEXT("owner"), Owner);
                NodeJson->SetObjectField(TEXT("semantic"), Semantic);
                if (Operation != TEXT("node"))
                {
                    ++Counts.BlueprintSemanticNodes;
                }

                TArray<TSharedPtr<FJsonValue>> PinsJson;
                for (int32 PinIndex = 0; PinIndex < Node->Pins.Num(); ++PinIndex)
                {
                    UEdGraphPin* Pin = Node->Pins[PinIndex];
                    if (!Pin)
                    {
                        continue;
                    }
                    const FString PinId = MakePinId(NodeId, Pin, PinIndex);
                    PinIds.Add(Pin, PinId);
                    if (SeenPinIds.Contains(PinId))
                    {
                        continue;
                    }
                    SeenPinIds.Add(PinId);

                    const TSharedRef<FJsonObject> PinJson = MakeShared<FJsonObject>();
                    PinJson->SetStringField(TEXT("pin_id"), PinId);
                    PinJson->SetStringField(TEXT("node_id"), NodeId);
                    PinJson->SetStringField(TEXT("blueprint_path"), ObjectPath);
                    PinJson->SetStringField(TEXT("graph_id"), GraphId);
                    PinJson->SetStringField(TEXT("graph_name"), Graph->GetName());
                    PinJson->SetNumberField(TEXT("pin_index"), PinIndex);
                    PinJson->SetStringField(TEXT("name"), Pin->PinName.ToString());
                    PinJson->SetStringField(TEXT("direction"), Pin->Direction == EGPD_Input ? TEXT("input") : TEXT("output"));
                    PinJson->SetObjectField(TEXT("type"), PinTypeToJson(Pin->PinType));
                    PinJson->SetStringField(TEXT("default_value"), Pin->DefaultValue);
                    PinJson->SetStringField(TEXT("default_object"), Pin->DefaultObject ? Pin->DefaultObject->GetPathName() : TEXT(""));
                    PinJson->SetStringField(TEXT("default_text"), Pin->DefaultTextValue.ToString());
                    PinJson->SetBoolField(TEXT("hidden"), Pin->bHidden);
                    PinJson->SetBoolField(TEXT("not_connectable"), Pin->bNotConnectable);
                    PinJson->SetNumberField(TEXT("linked_count"), Pin->LinkedTo.Num());
                    PinsJson.Add(MakeShared<FJsonValueObject>(PinJson));

                    if (!PinsWriter.Write(PinJson))
                    {
                        return false;
                    }
                    ++Counts.BlueprintPins;
                }
                NodeJson->SetArrayField(TEXT("pins"), PinsJson);

                if (!NodesWriter.Write(NodeJson))
                {
                    return false;
                }
                ++Counts.BlueprintNodes;

                if (!ScanNodeProperties(
                        Node,
                        NodeId,
                        ObjectPath,
                        Graph->GetName(),
                        PropertiesWriter,
                        ReferencesWriter,
                        Counts))
                {
                    return false;
                }

                if (!ScanNodeBindings(
                        Node,
                        NodeId,
                        ObjectPath,
                        Graph->GetName(),
                        BindingsWriter,
                        Counts))
                {
                    return false;
                }
            }

            TSet<FString> SeenEdgeKeys;
            for (UEdGraphNode* Node : Graph->Nodes)
            {
                if (!Node)
                {
                    continue;
                }
                for (UEdGraphPin* Pin : Node->Pins)
                {
                    if (!Pin || Pin->Direction != EGPD_Output)
                    {
                        continue;
                    }
                    const FString* SourcePinId = PinIds.Find(Pin);
                    if (!SourcePinId)
                    {
                        continue;
                    }

                    for (UEdGraphPin* LinkedPin : Pin->LinkedTo)
                    {
                        if (!LinkedPin)
                        {
                            continue;
                        }
                        const FString* TargetPinId = PinIds.Find(LinkedPin);
                        if (!TargetPinId)
                        {
                            continue;
                        }

                        const FString* SourceNodeId = NodeIds.Find(Node);
                        const FString* TargetNodeId = NodeIds.Find(LinkedPin->GetOwningNode());
                        if (!SourceNodeId || !TargetNodeId)
                        {
                            continue;
                        }

                        const FString EdgeKey = *SourcePinId + TEXT("->") + *TargetPinId;
                        if (SeenEdgeKeys.Contains(EdgeKey))
                        {
                            continue;
                        }
                        SeenEdgeKeys.Add(EdgeKey);

                        const TSharedRef<FJsonObject> EdgeJson = MakeShared<FJsonObject>();
                        EdgeJson->SetStringField(TEXT("blueprint_path"), ObjectPath);
                        EdgeJson->SetStringField(TEXT("graph_id"), GraphId);
                        EdgeJson->SetStringField(TEXT("graph_name"), Graph->GetName());
                        EdgeJson->SetStringField(TEXT("source_node_id"), *SourceNodeId);
                        EdgeJson->SetStringField(TEXT("source_pin_id"), *SourcePinId);
                        EdgeJson->SetStringField(TEXT("source_pin_name"), Pin->PinName.ToString());
                        EdgeJson->SetStringField(TEXT("target_node_id"), *TargetNodeId);
                        EdgeJson->SetStringField(TEXT("target_pin_id"), *TargetPinId);
                        EdgeJson->SetStringField(TEXT("target_pin_name"), LinkedPin->PinName.ToString());
                        EdgeJson->SetStringField(TEXT("pin_category"), Pin->PinType.PinCategory.ToString());
                        EdgeJson->SetStringField(
                            TEXT("edge_kind"),
                            Pin->PinType.PinCategory == FName(TEXT("exec")) ? TEXT("execution") : TEXT("data"));
                        if (!EdgesWriter.Write(EdgeJson))
                        {
                            return false;
                        }
                        ++Counts.BlueprintEdges;
                    }
                }
            }
        }

        if (!ScanRigVMObjects(
                Blueprint,
                ObjectPath,
                RigVMObjectsWriter,
                RigVMPinsWriter,
                RigVMLinksWriter,
                RigVMPropertiesWriter,
                RigVMReferencesWriter,
                bIncludeRawRigVMProperties,
                Counts))
        {
            return false;
        }

        return true;
    }


    static TArray<UObject*> GetReflectedObjectArray(UObject* Object, const FName PropertyName)
    {
        TArray<UObject*> Result;
        if (!Object)
        {
            return Result;
        }

        FArrayProperty* ArrayProperty = CastField<FArrayProperty>(
            Object->GetClass()->FindPropertyByName(PropertyName));
        FObjectPropertyBase* InnerObject = ArrayProperty
            ? CastField<FObjectPropertyBase>(ArrayProperty->Inner)
            : nullptr;
        if (!ArrayProperty || !InnerObject)
        {
            return Result;
        }

        const void* ArrayValue = ArrayProperty->ContainerPtrToValuePtr<void>(Object);
        FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
        Result.Reserve(Helper.Num());
        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            UObject* Value = InnerObject->GetObjectPropertyValue(Helper.GetRawPtr(Index));
            if (Value)
            {
                Result.Add(Value);
            }
        }
        return Result;
    }

    static TArray<UObject*> GetStructObjectArrayField(
        UStruct* Struct,
        const void* StructValue,
        const FName ArrayFieldName)
    {
        TArray<UObject*> Result;
        if (!Struct || !StructValue)
        {
            return Result;
        }

        FArrayProperty* ArrayProperty = CastField<FArrayProperty>(
            Struct->FindPropertyByName(ArrayFieldName));
        FObjectPropertyBase* InnerObject = ArrayProperty
            ? CastField<FObjectPropertyBase>(ArrayProperty->Inner)
            : nullptr;
        if (!ArrayProperty || !InnerObject)
        {
            return Result;
        }

        const void* ArrayValue = ArrayProperty->ContainerPtrToValuePtr<void>(StructValue);
        FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
        Result.Reserve(Helper.Num());
        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            UObject* Value = InnerObject->GetObjectPropertyValue(Helper.GetRawPtr(Index));
            if (Value)
            {
                Result.Add(Value);
            }
        }
        return Result;
    }

    static FString ExportStructFieldTextByName(
        UStruct* Struct,
        const void* StructValue,
        const FName FieldName,
        UObject* Owner,
        int32 MaxChars = 16384)
    {
        if (!Struct || !StructValue)
        {
            return TEXT("");
        }
        FProperty* Field = Struct->FindPropertyByName(FieldName);
        if (!Field)
        {
            return TEXT("");
        }
        const void* FieldValue = Field->ContainerPtrToValuePtr<void>(StructValue);
        FString Value;
        Field->ExportTextItem_Direct(Value, FieldValue, nullptr, Owner, PPF_None, nullptr);
        if (MaxChars > 0 && Value.Len() > MaxChars)
        {
            Value = Value.Left(MaxChars);
        }
        return Value;
    }

    static bool ScanAIObjectProperties(
        UObject* Object,
        const FString& AssetPath,
        const FString& System,
        const FString& OwnerKind,
        const FString& OwnerId,
        FJsonlWriter& Writer,
        FScanCounts& Counts)
    {
        if (!Object)
        {
            return true;
        }

        static constexpr int32 MaxChars = 32768;
        for (UClass* Class = Object->GetClass();
             Class && Class != UObject::StaticClass();
             Class = Class->GetSuperClass())
        {
            for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
            {
                FProperty* Property = *It;
                if (!IsCapturableProperty(Property))
                {
                    continue;
                }
                const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
                if (!ValuePtr)
                {
                    continue;
                }

                FString Value;
                Property->ExportTextItem_Direct(Value, ValuePtr, nullptr, Object, PPF_None, nullptr);
                bool bTruncated = false;
                if (Value.Len() > MaxChars)
                {
                    Value = Value.Left(MaxChars);
                    bTruncated = true;
                }

                UObject* ObjectValue = nullptr;
                if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
                {
                    ObjectValue = ObjectProperty->GetObjectPropertyValue(ValuePtr);
                }

                const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
                Json->SetStringField(TEXT("asset_path"), AssetPath);
                Json->SetStringField(TEXT("system"), System);
                Json->SetStringField(TEXT("owner_kind"), OwnerKind);
                Json->SetStringField(TEXT("owner_id"), OwnerId);
                Json->SetStringField(TEXT("owner_class"), Object->GetClass()->GetPathName());
                Json->SetStringField(TEXT("declaring_type"), Class->GetPathName());
                Json->SetStringField(TEXT("property_name"), Property->GetName());
                Json->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
                Json->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
                Json->SetStringField(TEXT("value"), Value);
                Json->SetStringField(TEXT("object_path"), ObjectValue ? ObjectValue->GetPathName() : TEXT(""));
                Json->SetStringField(TEXT("object_class"), ObjectValue ? ObjectValue->GetClass()->GetPathName() : TEXT(""));
                Json->SetNumberField(TEXT("property_flags"), static_cast<double>(Property->GetPropertyFlags()));
                Json->SetBoolField(TEXT("truncated"), bTruncated);
                if (!Writer.Write(Json))
                {
                    return false;
                }
                ++Counts.AIProperties;
            }
        }
        return true;
    }

    static FString BehaviorTreeNodeKind(UObject* Node)
    {
        if (!Node)
        {
            return TEXT("unknown");
        }
        const UClass* Class = Node->GetClass();
        if (ClassIsOrDerivedFromName(Class, TEXT("BTCompositeNode"))) return TEXT("composite");
        if (ClassIsOrDerivedFromName(Class, TEXT("BTTaskNode"))) return TEXT("task");
        if (ClassIsOrDerivedFromName(Class, TEXT("BTDecorator"))) return TEXT("decorator");
        if (ClassIsOrDerivedFromName(Class, TEXT("BTService"))) return TEXT("service");
        if (ClassIsOrDerivedFromName(Class, TEXT("BTAuxiliaryNode"))) return TEXT("auxiliary");
        return TEXT("node");
    }

    static bool WriteBehaviorTreeAttachmentNode(
        UObject* Node,
        const FString& AssetPath,
        const FString& AttachedTo,
        const FString& AttachmentKind,
        int32 AttachmentIndex,
        FJsonlWriter& NodesWriter,
        FJsonlWriter& PropertiesWriter,
        FScanCounts& Counts,
        TSet<FString>& SeenNodes)
    {
        if (!Node)
        {
            return true;
        }
        const FString NodeId = Node->GetPathName();
        if (!SeenNodes.Contains(NodeId))
        {
            SeenNodes.Add(NodeId);
            const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
            Json->SetStringField(TEXT("node_id"), NodeId);
            Json->SetStringField(TEXT("behavior_tree_path"), AssetPath);
            Json->SetStringField(TEXT("node_kind"), BehaviorTreeNodeKind(Node));
            Json->SetStringField(TEXT("class_path"), Node->GetClass()->GetPathName());
            Json->SetStringField(TEXT("class_name"), Node->GetClass()->GetName());
            Json->SetStringField(TEXT("name"), Node->GetName());
            Json->SetStringField(TEXT("display_name"), ExportReflectedPropertyText(Node, TEXT("NodeName")));
            Json->SetStringField(TEXT("attached_to"), AttachedTo);
            Json->SetStringField(TEXT("attachment_kind"), AttachmentKind);
            Json->SetNumberField(TEXT("attachment_index"), AttachmentIndex);
            if (!NodesWriter.Write(Json)) return false;
            ++Counts.BehaviorTreeNodes;
            if (!ScanAIObjectProperties(Node, AssetPath, TEXT("behavior_tree"), BehaviorTreeNodeKind(Node), NodeId, PropertiesWriter, Counts)) return false;
        }
        return true;
    }

    static bool ScanBehaviorTreeNodeRecursive(
        UObject* Node,
        const FString& AssetPath,
        const FString& ParentNodeId,
        int32 ChildIndex,
        FJsonlWriter& NodesWriter,
        FJsonlWriter& EdgesWriter,
        FJsonlWriter& PropertiesWriter,
        FScanCounts& Counts,
        TSet<FString>& SeenNodes)
    {
        if (!Node)
        {
            return true;
        }

        const FString NodeId = Node->GetPathName();
        if (!SeenNodes.Contains(NodeId))
        {
            SeenNodes.Add(NodeId);
            const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
            Json->SetStringField(TEXT("node_id"), NodeId);
            Json->SetStringField(TEXT("behavior_tree_path"), AssetPath);
            Json->SetStringField(TEXT("node_kind"), BehaviorTreeNodeKind(Node));
            Json->SetStringField(TEXT("class_path"), Node->GetClass()->GetPathName());
            Json->SetStringField(TEXT("class_name"), Node->GetClass()->GetName());
            Json->SetStringField(TEXT("name"), Node->GetName());
            Json->SetStringField(TEXT("display_name"), ExportReflectedPropertyText(Node, TEXT("NodeName")));
            Json->SetStringField(TEXT("parent_node_id"), ParentNodeId);
            Json->SetNumberField(TEXT("child_index"), ChildIndex);
            if (!NodesWriter.Write(Json)) return false;
            ++Counts.BehaviorTreeNodes;
            if (!ScanAIObjectProperties(Node, AssetPath, TEXT("behavior_tree"), BehaviorTreeNodeKind(Node), NodeId, PropertiesWriter, Counts)) return false;
        }

        if (!ParentNodeId.IsEmpty())
        {
            const TSharedRef<FJsonObject> Edge = MakeShared<FJsonObject>();
            Edge->SetStringField(TEXT("behavior_tree_path"), AssetPath);
            Edge->SetStringField(TEXT("source_node_id"), ParentNodeId);
            Edge->SetStringField(TEXT("target_node_id"), NodeId);
            Edge->SetStringField(TEXT("edge_kind"), TEXT("child"));
            Edge->SetNumberField(TEXT("child_index"), ChildIndex);
            Edge->SetStringField(TEXT("decorator_logic"), TEXT(""));
            Edge->SetArrayField(TEXT("decorator_ids"), TArray<TSharedPtr<FJsonValue>>());
            if (!EdgesWriter.Write(Edge)) return false;
            ++Counts.BehaviorTreeEdges;
        }

        if (BehaviorTreeNodeKind(Node) != TEXT("composite"))
        {
            return true;
        }

        const TArray<UObject*> Services = GetReflectedObjectArray(Node, TEXT("Services"));
        for (int32 ServiceIndex = 0; ServiceIndex < Services.Num(); ++ServiceIndex)
        {
            UObject* Service = Services[ServiceIndex];
            if (!WriteBehaviorTreeAttachmentNode(Service, AssetPath, NodeId, TEXT("service"), ServiceIndex, NodesWriter, PropertiesWriter, Counts, SeenNodes)) return false;
            const TSharedRef<FJsonObject> Edge = MakeShared<FJsonObject>();
            Edge->SetStringField(TEXT("behavior_tree_path"), AssetPath);
            Edge->SetStringField(TEXT("source_node_id"), NodeId);
            Edge->SetStringField(TEXT("target_node_id"), Service->GetPathName());
            Edge->SetStringField(TEXT("edge_kind"), TEXT("service"));
            Edge->SetNumberField(TEXT("child_index"), ServiceIndex);
            Edge->SetStringField(TEXT("decorator_logic"), TEXT(""));
            Edge->SetArrayField(TEXT("decorator_ids"), TArray<TSharedPtr<FJsonValue>>());
            if (!EdgesWriter.Write(Edge)) return false;
            ++Counts.BehaviorTreeEdges;
        }

        FArrayProperty* ChildrenProperty = CastField<FArrayProperty>(Node->GetClass()->FindPropertyByName(TEXT("Children")));
        FStructProperty* ChildStructProperty = ChildrenProperty ? CastField<FStructProperty>(ChildrenProperty->Inner) : nullptr;
        if (!ChildrenProperty || !ChildStructProperty || !ChildStructProperty->Struct)
        {
            return true;
        }

        const void* ChildrenValue = ChildrenProperty->ContainerPtrToValuePtr<void>(Node);
        FScriptArrayHelper ChildrenHelper(ChildrenProperty, ChildrenValue);
        for (int32 Index = 0; Index < ChildrenHelper.Num(); ++Index)
        {
            const void* ChildValue = ChildrenHelper.GetRawPtr(Index);
            UStruct* ChildStruct = ChildStructProperty->Struct;
            UObject* Child = GetStructObjectField(ChildStruct, ChildValue, TEXT("ChildComposite"));
            if (!Child) Child = GetStructObjectField(ChildStruct, ChildValue, TEXT("ChildTask"));
            if (!Child) continue;

            TArray<UObject*> Decorators = GetStructObjectArrayField(ChildStruct, ChildValue, TEXT("Decorators"));
            TArray<TSharedPtr<FJsonValue>> DecoratorIds;
            for (int32 DecoratorIndex = 0; DecoratorIndex < Decorators.Num(); ++DecoratorIndex)
            {
                UObject* Decorator = Decorators[DecoratorIndex];
                if (!WriteBehaviorTreeAttachmentNode(Decorator, AssetPath, Child->GetPathName(), TEXT("decorator"), DecoratorIndex, NodesWriter, PropertiesWriter, Counts, SeenNodes)) return false;
                DecoratorIds.Add(MakeShared<FJsonValueString>(Decorator->GetPathName()));
            }

            const TSharedRef<FJsonObject> Edge = MakeShared<FJsonObject>();
            Edge->SetStringField(TEXT("behavior_tree_path"), AssetPath);
            Edge->SetStringField(TEXT("source_node_id"), NodeId);
            Edge->SetStringField(TEXT("target_node_id"), Child->GetPathName());
            Edge->SetStringField(TEXT("edge_kind"), TEXT("child"));
            Edge->SetNumberField(TEXT("child_index"), Index);
            Edge->SetStringField(TEXT("decorator_logic"), ExportStructFieldTextByName(ChildStruct, ChildValue, TEXT("DecoratorOps"), Node));
            Edge->SetArrayField(TEXT("decorator_ids"), DecoratorIds);
            if (!EdgesWriter.Write(Edge)) return false;
            ++Counts.BehaviorTreeEdges;

            if (!ScanBehaviorTreeNodeRecursive(Child, AssetPath, TEXT(""), Index, NodesWriter, EdgesWriter, PropertiesWriter, Counts, SeenNodes)) return false;
        }
        return true;
    }

    static bool ScanBehaviorTreeAsset(
        UObject* Tree,
        const FString& AssetPath,
        FJsonlWriter& TreesWriter,
        FJsonlWriter& NodesWriter,
        FJsonlWriter& EdgesWriter,
        FJsonlWriter& PropertiesWriter,
        FScanCounts& Counts)
    {
        if (!Tree) return true;
        UObject* RootNode = GetReflectedObjectProperty(Tree, TEXT("RootNode"));
        UObject* Blackboard = GetReflectedObjectProperty(Tree, TEXT("BlackboardAsset"));
        const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
        Json->SetStringField(TEXT("behavior_tree_path"), AssetPath);
        Json->SetStringField(TEXT("class_path"), Tree->GetClass()->GetPathName());
        Json->SetStringField(TEXT("root_node_id"), RootNode ? RootNode->GetPathName() : TEXT(""));
        Json->SetStringField(TEXT("blackboard_path"), Blackboard ? Blackboard->GetPathName() : TEXT(""));
        Json->SetNumberField(TEXT("root_decorator_count"), GetReflectedObjectArray(Tree, TEXT("RootDecorators")).Num());
        Json->SetStringField(TEXT("root_decorator_logic"), ExportReflectedPropertyText(Tree, TEXT("RootDecoratorOps")));
        if (!TreesWriter.Write(Json)) return false;
        ++Counts.BehaviorTrees;
        if (!ScanAIObjectProperties(Tree, AssetPath, TEXT("behavior_tree"), TEXT("tree"), AssetPath, PropertiesWriter, Counts)) return false;

        TSet<FString> SeenNodes;
        if (RootNode && !ScanBehaviorTreeNodeRecursive(RootNode, AssetPath, TEXT(""), 0, NodesWriter, EdgesWriter, PropertiesWriter, Counts, SeenNodes)) return false;

        TArray<UObject*> RootDecorators = GetReflectedObjectArray(Tree, TEXT("RootDecorators"));
        for (int32 Index = 0; Index < RootDecorators.Num(); ++Index)
        {
            UObject* Decorator = RootDecorators[Index];
            if (!WriteBehaviorTreeAttachmentNode(Decorator, AssetPath, RootNode ? RootNode->GetPathName() : AssetPath, TEXT("root_decorator"), Index, NodesWriter, PropertiesWriter, Counts, SeenNodes)) return false;
        }
        return true;
    }

    static bool ScanBlackboardAsset(
        UObject* Blackboard,
        const FString& AssetPath,
        FJsonlWriter& BlackboardsWriter,
        FJsonlWriter& KeysWriter,
        FJsonlWriter& PropertiesWriter,
        FScanCounts& Counts)
    {
        if (!Blackboard) return true;
        UObject* Parent = GetReflectedObjectProperty(Blackboard, TEXT("Parent"));
        const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
        Json->SetStringField(TEXT("blackboard_path"), AssetPath);
        Json->SetStringField(TEXT("class_path"), Blackboard->GetClass()->GetPathName());
        Json->SetStringField(TEXT("parent_blackboard_path"), Parent ? Parent->GetPathName() : TEXT(""));
        if (!BlackboardsWriter.Write(Json)) return false;
        ++Counts.Blackboards;
        if (!ScanAIObjectProperties(Blackboard, AssetPath, TEXT("blackboard"), TEXT("blackboard"), AssetPath, PropertiesWriter, Counts)) return false;

        FArrayProperty* KeysProperty = CastField<FArrayProperty>(Blackboard->GetClass()->FindPropertyByName(TEXT("Keys")));
        FStructProperty* KeyStructProperty = KeysProperty ? CastField<FStructProperty>(KeysProperty->Inner) : nullptr;
        if (!KeysProperty || !KeyStructProperty || !KeyStructProperty->Struct) return true;
        const void* KeysValue = KeysProperty->ContainerPtrToValuePtr<void>(Blackboard);
        FScriptArrayHelper Helper(KeysProperty, KeysValue);
        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            const void* KeyValue = Helper.GetRawPtr(Index);
            UStruct* KeyStruct = KeyStructProperty->Struct;
            const FString KeyName = ExportStructFieldTextByName(KeyStruct, KeyValue, TEXT("EntryName"), Blackboard);
            UObject* KeyType = GetStructObjectField(KeyStruct, KeyValue, TEXT("KeyType"));
            const FString KeyId = FString::Printf(TEXT("%s#key:%d:%s"), *AssetPath, Index, *KeyName);
            const TSharedRef<FJsonObject> KeyJson = MakeShared<FJsonObject>();
            KeyJson->SetStringField(TEXT("key_id"), KeyId);
            KeyJson->SetStringField(TEXT("blackboard_path"), AssetPath);
            KeyJson->SetNumberField(TEXT("key_index"), Index);
            KeyJson->SetStringField(TEXT("name"), KeyName);
            KeyJson->SetStringField(TEXT("category"), ExportStructFieldTextByName(KeyStruct, KeyValue, TEXT("EntryCategory"), Blackboard));
            KeyJson->SetStringField(TEXT("description"), ExportStructFieldTextByName(KeyStruct, KeyValue, TEXT("EntryDescription"), Blackboard));
            KeyJson->SetStringField(TEXT("key_type_path"), KeyType ? KeyType->GetPathName() : TEXT(""));
            KeyJson->SetStringField(TEXT("key_type_class"), KeyType ? KeyType->GetClass()->GetPathName() : TEXT(""));
            KeyJson->SetStringField(TEXT("instance_synced"), ExportStructFieldTextByName(KeyStruct, KeyValue, TEXT("bInstanceSynced"), Blackboard));
            FString RawKeyValue;
            KeyStructProperty->ExportTextItem_Direct(RawKeyValue, KeyValue, nullptr, Blackboard, PPF_None, nullptr);
            if (RawKeyValue.Len() > 32768) RawKeyValue = RawKeyValue.Left(32768);
            KeyJson->SetStringField(TEXT("raw_value"), RawKeyValue);
            if (!KeysWriter.Write(KeyJson)) return false;
            ++Counts.BlackboardKeys;
            if (KeyType && !ScanAIObjectProperties(KeyType, AssetPath, TEXT("blackboard"), TEXT("key_type"), KeyId, PropertiesWriter, Counts)) return false;
        }
        return true;
    }

    static bool ScanEQSAsset(
        UObject* Query,
        const FString& AssetPath,
        FJsonlWriter& QueriesWriter,
        FJsonlWriter& OptionsWriter,
        FJsonlWriter& GeneratorsWriter,
        FJsonlWriter& TestsWriter,
        FJsonlWriter& PropertiesWriter,
        FScanCounts& Counts)
    {
        if (!Query) return true;
        TArray<UObject*> Options = GetReflectedObjectArray(Query, TEXT("Options"));
        if (Options.IsEmpty())
        {
            TArray<UObject*> Owned;
            GetObjectsWithOuter(Query, Owned, EGetObjectsFlags::IncludeNestedObjects);
            for (UObject* OwnedObject : Owned)
            {
                if (OwnedObject && ClassIsOrDerivedFromName(OwnedObject->GetClass(), TEXT("EnvQueryOption")))
                {
                    Options.Add(OwnedObject);
                }
            }
            Options.Sort([](const UObject& A, const UObject& B) { return A.GetPathName() < B.GetPathName(); });
        }
        const TSharedRef<FJsonObject> QueryJson = MakeShared<FJsonObject>();
        QueryJson->SetStringField(TEXT("eqs_path"), AssetPath);
        QueryJson->SetStringField(TEXT("class_path"), Query->GetClass()->GetPathName());
        QueryJson->SetNumberField(TEXT("option_count"), Options.Num());
        if (!QueriesWriter.Write(QueryJson)) return false;
        ++Counts.EQSQueries;
        if (!ScanAIObjectProperties(Query, AssetPath, TEXT("eqs"), TEXT("query"), AssetPath, PropertiesWriter, Counts)) return false;

        for (int32 OptionIndex = 0; OptionIndex < Options.Num(); ++OptionIndex)
        {
            UObject* Option = Options[OptionIndex];
            UObject* Generator = GetReflectedObjectProperty(Option, TEXT("Generator"));
            TArray<UObject*> Tests = GetReflectedObjectArray(Option, TEXT("Tests"));
            const FString OptionId = Option ? Option->GetPathName() : FString::Printf(TEXT("%s#option:%d"), *AssetPath, OptionIndex);
            const TSharedRef<FJsonObject> OptionJson = MakeShared<FJsonObject>();
            OptionJson->SetStringField(TEXT("option_id"), OptionId);
            OptionJson->SetStringField(TEXT("eqs_path"), AssetPath);
            OptionJson->SetNumberField(TEXT("option_index"), OptionIndex);
            OptionJson->SetStringField(TEXT("class_path"), Option ? Option->GetClass()->GetPathName() : TEXT(""));
            OptionJson->SetStringField(TEXT("generator_id"), Generator ? Generator->GetPathName() : TEXT(""));
            OptionJson->SetNumberField(TEXT("test_count"), Tests.Num());
            if (!OptionsWriter.Write(OptionJson)) return false;
            ++Counts.EQSOptions;
            if (Option && !ScanAIObjectProperties(Option, AssetPath, TEXT("eqs"), TEXT("option"), OptionId, PropertiesWriter, Counts)) return false;

            if (Generator)
            {
                const TSharedRef<FJsonObject> GeneratorJson = MakeShared<FJsonObject>();
                GeneratorJson->SetStringField(TEXT("generator_id"), Generator->GetPathName());
                GeneratorJson->SetStringField(TEXT("eqs_path"), AssetPath);
                GeneratorJson->SetStringField(TEXT("option_id"), OptionId);
                GeneratorJson->SetNumberField(TEXT("option_index"), OptionIndex);
                GeneratorJson->SetStringField(TEXT("class_path"), Generator->GetClass()->GetPathName());
                GeneratorJson->SetStringField(TEXT("class_name"), Generator->GetClass()->GetName());
                GeneratorJson->SetStringField(TEXT("item_type"), ExportReflectedPropertyText(Generator, TEXT("ItemType")));
                if (!GeneratorsWriter.Write(GeneratorJson)) return false;
                ++Counts.EQSGenerators;
                if (!ScanAIObjectProperties(Generator, AssetPath, TEXT("eqs"), TEXT("generator"), Generator->GetPathName(), PropertiesWriter, Counts)) return false;
            }

            for (int32 TestIndex = 0; TestIndex < Tests.Num(); ++TestIndex)
            {
                UObject* Test = Tests[TestIndex];
                const TSharedRef<FJsonObject> TestJson = MakeShared<FJsonObject>();
                TestJson->SetStringField(TEXT("test_id"), Test->GetPathName());
                TestJson->SetStringField(TEXT("eqs_path"), AssetPath);
                TestJson->SetStringField(TEXT("option_id"), OptionId);
                TestJson->SetNumberField(TEXT("option_index"), OptionIndex);
                TestJson->SetNumberField(TEXT("test_index"), TestIndex);
                TestJson->SetStringField(TEXT("class_path"), Test->GetClass()->GetPathName());
                TestJson->SetStringField(TEXT("class_name"), Test->GetClass()->GetName());
                TestJson->SetStringField(TEXT("test_purpose"), ExportReflectedPropertyText(Test, TEXT("TestPurpose")));
                TestJson->SetStringField(TEXT("filter_type"), ExportReflectedPropertyText(Test, TEXT("FilterType")));
                TestJson->SetStringField(TEXT("scoring_equation"), ExportReflectedPropertyText(Test, TEXT("ScoringEquation")));
                FString ScoringFactor = ExportReflectedPropertyText(Test, TEXT("ScoringFactor"));
                if (ScoringFactor.IsEmpty()) ScoringFactor = ExportReflectedPropertyText(Test, TEXT("WeightModifier"));
                TestJson->SetStringField(TEXT("weight_modifier"), ScoringFactor);
                if (!TestsWriter.Write(TestJson)) return false;
                ++Counts.EQSTests;
                if (!ScanAIObjectProperties(Test, AssetPath, TEXT("eqs"), TEXT("test"), Test->GetPathName(), PropertiesWriter, Counts)) return false;
            }
        }
        return true;
    }

    static bool WriteStateTreeEditorNodeStruct(
        UStruct* NodeStruct,
        const void* NodeValue,
        UObject* Owner,
        const FString& AssetPath,
        const FString& StateId,
        const FString& Role,
        int32 NodeIndex,
        FJsonlWriter& NodesWriter,
        FJsonlWriter& PropertiesWriter,
        FScanCounts& Counts)
    {
        if (!NodeStruct || !NodeValue) return true;
        const FString Guid = ExportStructFieldTextByName(NodeStruct, NodeValue, TEXT("ID"), Owner);
        UObject* InstanceObject = GetStructObjectField(NodeStruct, NodeValue, TEXT("InstanceObject"));
        const FString RawNode = ExportStructFieldTextByName(NodeStruct, NodeValue, TEXT("Node"), Owner, 32768);
        const FString RawInstance = ExportStructFieldTextByName(NodeStruct, NodeValue, TEXT("Instance"), Owner, 32768);
        const bool bEmptyNode = !InstanceObject
            && (RawNode.IsEmpty() || RawNode == TEXT("None"))
            && (RawInstance.IsEmpty() || RawInstance == TEXT("None"));
        if (bEmptyNode)
        {
            return true;
        }

        const FString NodeId = !Guid.IsEmpty()
            ? FString::Printf(TEXT("%s#node:%s"), *AssetPath, *Guid)
            : FString::Printf(TEXT("%s#%s:%s:%d"), *AssetPath, *Role, *StateId, NodeIndex);
        const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
        Json->SetStringField(TEXT("node_id"), NodeId);
        Json->SetStringField(TEXT("statetree_path"), AssetPath);
        Json->SetStringField(TEXT("state_id"), StateId);
        Json->SetStringField(TEXT("role"), Role);
        Json->SetNumberField(TEXT("node_index"), NodeIndex);
        Json->SetStringField(TEXT("guid"), Guid);
        Json->SetStringField(TEXT("expression_indent"), ExportStructFieldTextByName(NodeStruct, NodeValue, TEXT("ExpressionIndent"), Owner));
        Json->SetStringField(TEXT("expression_operand"), ExportStructFieldTextByName(NodeStruct, NodeValue, TEXT("ExpressionOperand"), Owner));
        Json->SetStringField(TEXT("instance_object_path"), InstanceObject ? InstanceObject->GetPathName() : TEXT(""));
        Json->SetStringField(TEXT("instance_object_class"), InstanceObject ? InstanceObject->GetClass()->GetPathName() : TEXT(""));
        Json->SetStringField(TEXT("raw_node"), RawNode);
        Json->SetStringField(TEXT("raw_instance"), RawInstance);
        if (!NodesWriter.Write(Json)) return false;
        ++Counts.StateTreeNodes;
        if (InstanceObject && !ScanAIObjectProperties(InstanceObject, AssetPath, TEXT("statetree"), Role, NodeId, PropertiesWriter, Counts)) return false;
        return true;
    }

    static bool ScanStateTreeEditorNodeArray(
        UObject* Owner,
        const FString& PropertyName,
        const FString& AssetPath,
        const FString& StateId,
        const FString& Role,
        FJsonlWriter& NodesWriter,
        FJsonlWriter& PropertiesWriter,
        FScanCounts& Counts)
    {
        if (!Owner) return true;
        FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Owner->GetClass()->FindPropertyByName(FName(*PropertyName)));
        FStructProperty* InnerStruct = ArrayProperty ? CastField<FStructProperty>(ArrayProperty->Inner) : nullptr;
        if (!ArrayProperty || !InnerStruct || !InnerStruct->Struct) return true;
        const void* ArrayValue = ArrayProperty->ContainerPtrToValuePtr<void>(Owner);
        FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            if (!WriteStateTreeEditorNodeStruct(InnerStruct->Struct, Helper.GetRawPtr(Index), Owner, AssetPath, StateId, Role, Index, NodesWriter, PropertiesWriter, Counts)) return false;
        }
        return true;
    }

    static bool ScanStateTreeStateRecursive(
        UObject* State,
        const FString& AssetPath,
        const FString& ParentStateId,
        int32 ChildIndex,
        FJsonlWriter& StatesWriter,
        FJsonlWriter& NodesWriter,
        FJsonlWriter& TransitionsWriter,
        FJsonlWriter& PropertiesWriter,
        FScanCounts& Counts)
    {
        if (!State) return true;
        FString StateId = ExportReflectedPropertyText(State, TEXT("ID"));
        if (StateId.IsEmpty()) StateId = State->GetPathName();
        const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
        Json->SetStringField(TEXT("state_id"), StateId);
        Json->SetStringField(TEXT("statetree_path"), AssetPath);
        Json->SetStringField(TEXT("state_object_path"), State->GetPathName());
        Json->SetStringField(TEXT("parent_state_id"), ParentStateId);
        Json->SetNumberField(TEXT("child_index"), ChildIndex);
        Json->SetStringField(TEXT("name"), ExportReflectedPropertyText(State, TEXT("Name")));
        Json->SetStringField(TEXT("description"), ExportReflectedPropertyText(State, TEXT("Description")));
        Json->SetStringField(TEXT("state_type"), ExportReflectedPropertyText(State, TEXT("Type")));
        Json->SetStringField(TEXT("selection_behavior"), ExportReflectedPropertyText(State, TEXT("SelectionBehavior")));
        Json->SetStringField(TEXT("enabled"), ExportReflectedPropertyText(State, TEXT("bEnabled")));
        Json->SetStringField(TEXT("tag"), ExportReflectedPropertyText(State, TEXT("Tag")));
        Json->SetStringField(TEXT("tasks_completion"), ExportReflectedPropertyText(State, TEXT("TasksCompletion")));
        Json->SetStringField(TEXT("required_event"), ExportReflectedPropertyText(State, TEXT("RequiredEventToEnter")));
        UObject* LinkedAsset = GetReflectedObjectProperty(State, TEXT("LinkedAsset"));
        Json->SetStringField(TEXT("linked_asset"), LinkedAsset ? LinkedAsset->GetPathName() : TEXT(""));
        Json->SetStringField(TEXT("linked_subtree"), ExportReflectedPropertyText(State, TEXT("LinkedSubtree")));
        if (!StatesWriter.Write(Json)) return false;
        ++Counts.StateTreeStates;
        if (!ScanAIObjectProperties(State, AssetPath, TEXT("statetree"), TEXT("state"), StateId, PropertiesWriter, Counts)) return false;

        if (!ScanStateTreeEditorNodeArray(State, TEXT("EnterConditions"), AssetPath, StateId, TEXT("enter_condition"), NodesWriter, PropertiesWriter, Counts)) return false;
        if (!ScanStateTreeEditorNodeArray(State, TEXT("Tasks"), AssetPath, StateId, TEXT("task"), NodesWriter, PropertiesWriter, Counts)) return false;
        if (!ScanStateTreeEditorNodeArray(State, TEXT("Considerations"), AssetPath, StateId, TEXT("consideration"), NodesWriter, PropertiesWriter, Counts)) return false;

        FStructProperty* SingleTask = CastField<FStructProperty>(State->GetClass()->FindPropertyByName(TEXT("SingleTask")));
        if (SingleTask && SingleTask->Struct)
        {
            const void* Value = SingleTask->ContainerPtrToValuePtr<void>(State);
            const FString Raw = ExportStructFieldTextByName(SingleTask->Struct, Value, TEXT("ID"), State);
            if (!Raw.IsEmpty() && !WriteStateTreeEditorNodeStruct(SingleTask->Struct, Value, State, AssetPath, StateId, TEXT("single_task"), 0, NodesWriter, PropertiesWriter, Counts)) return false;
        }

        FArrayProperty* TransitionsProperty = CastField<FArrayProperty>(State->GetClass()->FindPropertyByName(TEXT("Transitions")));
        FStructProperty* TransitionStruct = TransitionsProperty ? CastField<FStructProperty>(TransitionsProperty->Inner) : nullptr;
        if (TransitionsProperty && TransitionStruct && TransitionStruct->Struct)
        {
            const void* ArrayValue = TransitionsProperty->ContainerPtrToValuePtr<void>(State);
            FScriptArrayHelper Helper(TransitionsProperty, ArrayValue);
            for (int32 Index = 0; Index < Helper.Num(); ++Index)
            {
                const void* Value = Helper.GetRawPtr(Index);
                UStruct* Struct = TransitionStruct->Struct;
                FString TransitionId = ExportStructFieldTextByName(Struct, Value, TEXT("ID"), State);
                if (TransitionId.IsEmpty()) TransitionId = FString::Printf(TEXT("%s#transition:%d"), *StateId, Index);
                const TSharedRef<FJsonObject> TransitionJson = MakeShared<FJsonObject>();
                TransitionJson->SetStringField(TEXT("transition_id"), TransitionId);
                TransitionJson->SetStringField(TEXT("statetree_path"), AssetPath);
                TransitionJson->SetStringField(TEXT("source_state_id"), StateId);
                TransitionJson->SetNumberField(TEXT("transition_index"), Index);
                TransitionJson->SetStringField(TEXT("trigger"), ExportStructFieldTextByName(Struct, Value, TEXT("Trigger"), State));
                TransitionJson->SetStringField(TEXT("event_tag"), ExportStructFieldTextByName(Struct, Value, TEXT("EventTag"), State));
                TransitionJson->SetStringField(TEXT("state"), ExportStructFieldTextByName(Struct, Value, TEXT("State"), State));
                TransitionJson->SetStringField(TEXT("priority"), ExportStructFieldTextByName(Struct, Value, TEXT("Priority"), State));
                TransitionJson->SetStringField(TEXT("fallback"), ExportStructFieldTextByName(Struct, Value, TEXT("Fallback"), State));
                TransitionJson->SetStringField(TEXT("enabled"), ExportStructFieldTextByName(Struct, Value, TEXT("bTransitionEnabled"), State));
                TransitionJson->SetStringField(TEXT("delay_enabled"), ExportStructFieldTextByName(Struct, Value, TEXT("bDelayTransition"), State));
                TransitionJson->SetStringField(TEXT("delay"), ExportStructFieldTextByName(Struct, Value, TEXT("DelayDuration"), State));
                FString RawTransition;
                TransitionStruct->ExportTextItem_Direct(RawTransition, Value, nullptr, State, PPF_None, nullptr);
                if (RawTransition.Len() > 32768) RawTransition = RawTransition.Left(32768);
                TransitionJson->SetStringField(TEXT("raw_value"), RawTransition);
                if (!TransitionsWriter.Write(TransitionJson)) return false;
                ++Counts.StateTreeTransitions;

                FArrayProperty* ConditionsProperty = CastField<FArrayProperty>(Struct->FindPropertyByName(TEXT("Conditions")));
                FStructProperty* ConditionStruct = ConditionsProperty ? CastField<FStructProperty>(ConditionsProperty->Inner) : nullptr;
                if (ConditionsProperty && ConditionStruct && ConditionStruct->Struct)
                {
                    const void* ConditionsValue = ConditionsProperty->ContainerPtrToValuePtr<void>(Value);
                    FScriptArrayHelper ConditionsHelper(ConditionsProperty, ConditionsValue);
                    for (int32 ConditionIndex = 0; ConditionIndex < ConditionsHelper.Num(); ++ConditionIndex)
                    {
                        if (!WriteStateTreeEditorNodeStruct(ConditionStruct->Struct, ConditionsHelper.GetRawPtr(ConditionIndex), State, AssetPath, StateId, TEXT("transition_condition"), ConditionIndex, NodesWriter, PropertiesWriter, Counts)) return false;
                    }
                }
            }
        }

        TArray<UObject*> Children = GetReflectedObjectArray(State, TEXT("Children"));
        for (int32 Index = 0; Index < Children.Num(); ++Index)
        {
            if (!ScanStateTreeStateRecursive(Children[Index], AssetPath, StateId, Index, StatesWriter, NodesWriter, TransitionsWriter, PropertiesWriter, Counts)) return false;
        }
        return true;
    }

    static bool ScanStateTreeBindings(
        UObject* EditorData,
        const FString& AssetPath,
        FJsonlWriter& BindingsWriter,
        FScanCounts& Counts)
    {
        if (!EditorData) return true;
        FStructProperty* EditorBindings = CastField<FStructProperty>(EditorData->GetClass()->FindPropertyByName(TEXT("EditorBindings")));
        if (!EditorBindings || !EditorBindings->Struct) return true;
        const void* BindingsValue = EditorBindings->ContainerPtrToValuePtr<void>(EditorData);
        FArrayProperty* PropertyBindings = CastField<FArrayProperty>(EditorBindings->Struct->FindPropertyByName(TEXT("PropertyBindings")));
        FStructProperty* BindingStruct = PropertyBindings ? CastField<FStructProperty>(PropertyBindings->Inner) : nullptr;
        if (!PropertyBindings || !BindingStruct || !BindingStruct->Struct) return true;
        const void* ArrayValue = PropertyBindings->ContainerPtrToValuePtr<void>(BindingsValue);
        FScriptArrayHelper Helper(PropertyBindings, ArrayValue);
        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            const void* Value = Helper.GetRawPtr(Index);
            const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
            Json->SetStringField(TEXT("statetree_path"), AssetPath);
            Json->SetNumberField(TEXT("binding_index"), Index);
            Json->SetStringField(TEXT("binding_struct"), BindingStruct->Struct->GetPathName());
            Json->SetStringField(TEXT("source_path"), ExportStructFieldTextByName(BindingStruct->Struct, Value, TEXT("SourcePropertyPath"), EditorData));
            Json->SetStringField(TEXT("target_path"), ExportStructFieldTextByName(BindingStruct->Struct, Value, TEXT("TargetPropertyPath"), EditorData));
            Json->SetStringField(TEXT("output_binding"), ExportStructFieldTextByName(BindingStruct->Struct, Value, TEXT("bIsOutputBinding"), EditorData));
            FString Raw;
            BindingStruct->ExportTextItem_Direct(Raw, Value, nullptr, EditorData, PPF_None, nullptr);
            if (Raw.Len() > 32768) Raw = Raw.Left(32768);
            Json->SetStringField(TEXT("raw_value"), Raw);
            if (!BindingsWriter.Write(Json)) return false;
            ++Counts.StateTreeBindings;
        }
        return true;
    }

    static bool ScanStateTreeAsset(
        UObject* Tree,
        const FString& AssetPath,
        FJsonlWriter& TreesWriter,
        FJsonlWriter& StatesWriter,
        FJsonlWriter& NodesWriter,
        FJsonlWriter& TransitionsWriter,
        FJsonlWriter& BindingsWriter,
        FJsonlWriter& PropertiesWriter,
        FScanCounts& Counts)
    {
        if (!Tree) return true;
        UObject* EditorData = GetReflectedObjectProperty(Tree, TEXT("EditorData"));
        if (!EditorData)
        {
            TArray<UObject*> Owned;
            GetObjectsWithOuter(Tree, Owned, EGetObjectsFlags::IncludeNestedObjects);
            for (UObject* OwnedObject : Owned)
            {
                if (OwnedObject && ClassIsOrDerivedFromName(OwnedObject->GetClass(), TEXT("StateTreeEditorData")))
                {
                    EditorData = OwnedObject;
                    break;
                }
            }
        }
        const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
        Json->SetStringField(TEXT("statetree_path"), AssetPath);
        Json->SetStringField(TEXT("class_path"), Tree->GetClass()->GetPathName());
        Json->SetStringField(TEXT("editor_data_path"), EditorData ? EditorData->GetPathName() : TEXT(""));
        Json->SetStringField(TEXT("editor_data_class"), EditorData ? EditorData->GetClass()->GetPathName() : TEXT(""));
        Json->SetStringField(TEXT("last_compiled_editor_data_hash"), ExportReflectedPropertyText(Tree, TEXT("LastCompiledEditorDataHash")));
        if (!TreesWriter.Write(Json)) return false;
        ++Counts.StateTrees;
        if (!ScanAIObjectProperties(Tree, AssetPath, TEXT("statetree"), TEXT("tree"), AssetPath, PropertiesWriter, Counts)) return false;
        if (!EditorData) return true;
        if (!ScanAIObjectProperties(EditorData, AssetPath, TEXT("statetree"), TEXT("editor_data"), EditorData->GetPathName(), PropertiesWriter, Counts)) return false;
        if (!ScanStateTreeEditorNodeArray(EditorData, TEXT("Evaluators"), AssetPath, TEXT(""), TEXT("evaluator"), NodesWriter, PropertiesWriter, Counts)) return false;
        if (!ScanStateTreeEditorNodeArray(EditorData, TEXT("GlobalTasks"), AssetPath, TEXT(""), TEXT("global_task"), NodesWriter, PropertiesWriter, Counts)) return false;
        if (!ScanStateTreeBindings(EditorData, AssetPath, BindingsWriter, Counts)) return false;
        TArray<UObject*> SubTrees = GetReflectedObjectArray(EditorData, TEXT("SubTrees"));
        for (int32 Index = 0; Index < SubTrees.Num(); ++Index)
        {
            if (!ScanStateTreeStateRecursive(SubTrees[Index], AssetPath, TEXT(""), Index, StatesWriter, NodesWriter, TransitionsWriter, PropertiesWriter, Counts)) return false;
        }
        return true;
    }


    static FString ExportObjectPropertyByName(UObject* Object, const FName PropertyName, int32 MaxChars = 16384)
    {
        if (!Object)
        {
            return TEXT("");
        }
        FProperty* Property = Object->GetClass()->FindPropertyByName(PropertyName);
        if (!Property)
        {
            return TEXT("");
        }
        const void* Value = Property->ContainerPtrToValuePtr<void>(Object);
        if (!Value)
        {
            return TEXT("");
        }
        FString Text;
        Property->ExportTextItem_Direct(Text, Value, nullptr, Object, PPF_None, nullptr);
        if (MaxChars > 0 && Text.Len() > MaxChars)
        {
            Text = Text.Left(MaxChars);
        }
        return Text;
    }

    static bool ScanVisualObjectProperties(
        UObject* Object,
        const FString& AssetPath,
        const FString& System,
        const FString& OwnerKind,
        const FString& OwnerId,
        FJsonlWriter& Writer,
        int64& Counter)
    {
        if (!Object)
        {
            return true;
        }

        static constexpr int32 MaxChars = 32768;
        for (UClass* Class = Object->GetClass(); Class && Class != UObject::StaticClass(); Class = Class->GetSuperClass())
        {
            for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
            {
                FProperty* Property = *It;
                if (!IsCapturableProperty(Property))
                {
                    continue;
                }
                const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
                if (!ValuePtr)
                {
                    continue;
                }

                FString Value;
                Property->ExportTextItem_Direct(Value, ValuePtr, nullptr, Object, PPF_None, nullptr);
                bool bTruncated = false;
                if (Value.Len() > MaxChars)
                {
                    Value = Value.Left(MaxChars);
                    bTruncated = true;
                }

                UObject* ObjectValue = nullptr;
                if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
                {
                    ObjectValue = ObjectProperty->GetObjectPropertyValue(ValuePtr);
                }

                const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
                Json->SetStringField(TEXT("asset_path"), AssetPath);
                Json->SetStringField(TEXT("system"), System);
                Json->SetStringField(TEXT("owner_kind"), OwnerKind);
                Json->SetStringField(TEXT("owner_id"), OwnerId);
                Json->SetStringField(TEXT("owner_class"), Object->GetClass()->GetPathName());
                Json->SetStringField(TEXT("declaring_type"), Class->GetPathName());
                Json->SetStringField(TEXT("property_name"), Property->GetName());
                Json->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
                Json->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
                Json->SetStringField(TEXT("value"), Value);
                Json->SetStringField(TEXT("object_path"), ObjectValue ? ObjectValue->GetPathName() : TEXT(""));
                Json->SetStringField(TEXT("object_class"), ObjectValue ? ObjectValue->GetClass()->GetPathName() : TEXT(""));
                Json->SetNumberField(TEXT("property_flags"), static_cast<double>(Property->GetPropertyFlags()));
                Json->SetBoolField(TEXT("truncated"), bTruncated);
                if (!Writer.Write(Json))
                {
                    return false;
                }
                ++Counter;
            }
        }
        return true;
    }

    static UObject* PCGNodeSettingsObject(UObject* Node)
    {
        if (!Node)
        {
            return nullptr;
        }

        UObject* Settings = GetReflectedObjectProperty(Node, TEXT("SettingsInterface"));
        if (!Settings)
        {
            Settings = GetReflectedObjectProperty(Node, TEXT("Settings"));
        }
        if (Settings)
        {
            return Settings;
        }

        // UE's public PCG API exposes settings through accessors, while the serialized
        // backing property name can vary. Fall back to any reflected object property
        // whose value is a PCG settings/settings-interface object.
        for (UClass* Class = Node->GetClass(); Class && Class != UObject::StaticClass(); Class = Class->GetSuperClass())
        {
            for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
            {
                FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(*It);
                if (!ObjectProperty)
                {
                    continue;
                }
                const void* ValuePtr = ObjectProperty->ContainerPtrToValuePtr<void>(Node);
                UObject* Candidate = ValuePtr ? ObjectProperty->GetObjectPropertyValue(ValuePtr) : nullptr;
                if (Candidate &&
                    (ClassIsOrDerivedFromName(Candidate->GetClass(), TEXT("PCGSettingsInterface")) ||
                     ClassIsOrDerivedFromName(Candidate->GetClass(), TEXT("PCGSettings"))))
                {
                    return Candidate;
                }
            }
        }

        TArray<UObject*> OwnedObjects;
        GetObjectsWithOuter(Node, OwnedObjects, EGetObjectsFlags::IncludeNestedObjects);
        for (UObject* Candidate : OwnedObjects)
        {
            if (Candidate &&
                (ClassIsOrDerivedFromName(Candidate->GetClass(), TEXT("PCGSettingsInterface")) ||
                 ClassIsOrDerivedFromName(Candidate->GetClass(), TEXT("PCGSettings"))))
            {
                return Candidate;
            }
        }
        return nullptr;
    }

    static void GetPCGNodePinsByDirection(
        UObject* Node,
        const FString& Direction,
        TArray<UObject*>& OutPins)
    {
        OutPins.Reset();
        if (!Node)
        {
            return;
        }

        const FName PreferredName = Direction == TEXT("input")
            ? TEXT("InputPins")
            : TEXT("OutputPins");
        OutPins = GetReflectedObjectArray(Node, PreferredName);
        if (OutPins.Num() > 0)
        {
            return;
        }

        // Be tolerant of backing-field renames: find any reflected array of PCGPin
        // objects whose property name conveys the requested direction.
        for (UClass* Class = Node->GetClass(); Class && Class != UObject::StaticClass(); Class = Class->GetSuperClass())
        {
            for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
            {
                FArrayProperty* ArrayProperty = CastField<FArrayProperty>(*It);
                FObjectPropertyBase* InnerObject = ArrayProperty
                    ? CastField<FObjectPropertyBase>(ArrayProperty->Inner)
                    : nullptr;
                if (!ArrayProperty || !InnerObject)
                {
                    continue;
                }
                const FString PropertyName = ArrayProperty->GetName();
                if (!PropertyName.Contains(Direction, ESearchCase::IgnoreCase) ||
                    !PropertyName.Contains(TEXT("pin"), ESearchCase::IgnoreCase))
                {
                    continue;
                }

                const void* ArrayValue = ArrayProperty->ContainerPtrToValuePtr<void>(Node);
                if (!ArrayValue)
                {
                    continue;
                }
                FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
                for (int32 Index = 0; Index < Helper.Num(); ++Index)
                {
                    UObject* Candidate = InnerObject->GetObjectPropertyValue(Helper.GetRawPtr(Index));
                    if (Candidate && ClassIsOrDerivedFromName(Candidate->GetClass(), TEXT("PCGPin")))
                    {
                        OutPins.Add(Candidate);
                    }
                }
                if (OutPins.Num() > 0)
                {
                    return;
                }
            }
        }
    }

    static UObject* FindOuterPCGGraph(UObject* Object)
    {
        for (UObject* Outer = Object ? Object->GetOuter() : nullptr; Outer; Outer = Outer->GetOuter())
        {
            if (ClassIsOrDerivedFromName(Outer->GetClass(), TEXT("PCGGraph")))
            {
                return Outer;
            }
        }
        return nullptr;
    }

    static bool ScanPCGGraphAsset(
        UObject* Graph,
        const FString& AssetPath,
        FJsonlWriter& GraphsWriter,
        FJsonlWriter& NodesWriter,
        FJsonlWriter& PinsWriter,
        FJsonlWriter& EdgesWriter,
        FJsonlWriter& PropertiesWriter,
        FScanCounts& Counts)
    {
        if (!Graph)
        {
            return true;
        }

        TArray<UObject*> OwnedObjects;
        GetObjectsWithOuter(Graph, OwnedObjects, EGetObjectsFlags::IncludeNestedObjects);
        OwnedObjects.Sort([](const UObject& A, const UObject& B) { return A.GetPathName() < B.GetPathName(); });

        TArray<UObject*> Nodes;
        TArray<UObject*> Pins;
        TArray<UObject*> Edges;
        TArray<UObject*> EmbeddedGraphs;
        for (UObject* Object : OwnedObjects)
        {
            if (!Object) continue;
            if (ClassIsOrDerivedFromName(Object->GetClass(), TEXT("PCGGraph")))
            {
                if (FindOuterPCGGraph(Object) == Graph) EmbeddedGraphs.Add(Object);
                continue;
            }
            if (FindOuterPCGGraph(Object) != Graph) continue;
            if (ClassIsOrDerivedFromName(Object->GetClass(), TEXT("PCGNode"))) Nodes.Add(Object);
            else if (ClassIsOrDerivedFromName(Object->GetClass(), TEXT("PCGPin"))) Pins.Add(Object);
            else if (ClassIsOrDerivedFromName(Object->GetClass(), TEXT("PCGEdge"))) Edges.Add(Object);
        }

        const TSharedRef<FJsonObject> GraphJson = MakeShared<FJsonObject>();
        GraphJson->SetStringField(TEXT("pcg_path"), AssetPath);
        GraphJson->SetStringField(TEXT("class_path"), Graph->GetClass()->GetPathName());
        UObject* ParentGraph = FindOuterPCGGraph(Graph);
        GraphJson->SetStringField(TEXT("parent_graph_path"), ParentGraph ? ParentGraph->GetPathName() : TEXT(""));
        GraphJson->SetBoolField(TEXT("embedded"), ParentGraph != nullptr);
        TArray<TSharedPtr<FJsonValue>> EmbeddedJson;
        for (UObject* Embedded : EmbeddedGraphs)
        {
            EmbeddedJson.Add(MakeShared<FJsonValueString>(Embedded->GetPathName()));
        }
        GraphJson->SetArrayField(TEXT("embedded_subgraphs"), EmbeddedJson);
        GraphJson->SetNumberField(TEXT("node_count"), Nodes.Num());
        GraphJson->SetNumberField(TEXT("pin_count"), Pins.Num());
        GraphJson->SetNumberField(TEXT("edge_count"), Edges.Num());
        GraphJson->SetStringField(TEXT("user_parameters"), ExportObjectPropertyByName(Graph, TEXT("UserParameters"), 32768));
        GraphJson->SetStringField(TEXT("default_grid"), ExportObjectPropertyByName(Graph, TEXT("DefaultGrid")));
        if (!GraphsWriter.Write(GraphJson)) return false;
        ++Counts.PCGGraphs;
        if (!ScanVisualObjectProperties(Graph, AssetPath, TEXT("pcg"), TEXT("graph"), AssetPath, PropertiesWriter, Counts.PCGProperties)) return false;

        TMap<FString, FString> PinDirections;
        TMap<FString, int32> PinIndices;
        for (UObject* Node : Nodes)
        {
            const FString NodeId = Node->GetPathName();
            UObject* Settings = PCGNodeSettingsObject(Node);
            const TSharedRef<FJsonObject> NodeJson = MakeShared<FJsonObject>();
            NodeJson->SetStringField(TEXT("pcg_path"), AssetPath);
            NodeJson->SetStringField(TEXT("node_id"), NodeId);
            NodeJson->SetStringField(TEXT("node_class"), Node->GetClass()->GetPathName());
            NodeJson->SetStringField(TEXT("node_name"), Node->GetName());
            NodeJson->SetStringField(TEXT("node_title"), ExportObjectPropertyByName(Node, TEXT("NodeTitle")));
            NodeJson->SetStringField(TEXT("position_x"), ExportObjectPropertyByName(Node, TEXT("PositionX")));
            NodeJson->SetStringField(TEXT("position_y"), ExportObjectPropertyByName(Node, TEXT("PositionY")));
            NodeJson->SetStringField(TEXT("settings_path"), Settings ? Settings->GetPathName() : TEXT(""));
            NodeJson->SetStringField(TEXT("settings_class"), Settings ? Settings->GetClass()->GetPathName() : TEXT(""));
            NodeJson->SetStringField(TEXT("settings_name"), Settings ? Settings->GetName() : TEXT(""));
            NodeJson->SetStringField(TEXT("enabled"), ExportObjectPropertyByName(Node, TEXT("bEnabled")));
            if (!NodesWriter.Write(NodeJson)) return false;
            ++Counts.PCGNodes;
            if (!ScanVisualObjectProperties(Node, AssetPath, TEXT("pcg"), TEXT("node"), NodeId, PropertiesWriter, Counts.PCGProperties)) return false;
            if (Settings && !ScanVisualObjectProperties(Settings, AssetPath, TEXT("pcg"), TEXT("settings"), Settings->GetPathName(), PropertiesWriter, Counts.PCGProperties)) return false;

            const FString PinDirectionNames[] = { TEXT("input"), TEXT("output") };
            for (int32 DirectionIndex = 0; DirectionIndex < 2; ++DirectionIndex)
            {
                TArray<UObject*> NodePins;
                GetPCGNodePinsByDirection(Node, PinDirectionNames[DirectionIndex], NodePins);
                for (int32 Index = 0; Index < NodePins.Num(); ++Index)
                {
                    if (NodePins[Index])
                    {
                        PinDirections.Add(NodePins[Index]->GetPathName(), PinDirectionNames[DirectionIndex]);
                        PinIndices.Add(NodePins[Index]->GetPathName(), Index);
                    }
                }
            }
        }

        // Connected pins can still be classified even if a future UE version renames
        // the node's serialized input/output arrays. UPCGEdge names are historical:
        // InputPin is the upstream/source pin and OutputPin is downstream/target.
        for (UObject* Edge : Edges)
        {
            UObject* SourcePin = GetReflectedObjectProperty(Edge, TEXT("InputPin"));
            UObject* TargetPin = GetReflectedObjectProperty(Edge, TEXT("OutputPin"));
            if (SourcePin && !PinDirections.Contains(SourcePin->GetPathName()))
            {
                PinDirections.Add(SourcePin->GetPathName(), TEXT("output"));
            }
            if (TargetPin && !PinDirections.Contains(TargetPin->GetPathName()))
            {
                PinDirections.Add(TargetPin->GetPathName(), TEXT("input"));
            }
        }

        for (UObject* Pin : Pins)
        {
            const FString PinId = Pin->GetPathName();
            UObject* Node = GetReflectedObjectProperty(Pin, TEXT("Node"));
            const FString PropertiesRaw = ExportObjectPropertyByName(Pin, TEXT("Properties"), 32768);
            FString Label;
            FString AllowedTypes;
            FString Status;
            FString AllowMultiple;
            FString Invisible;
            if (FStructProperty* PinProps = CastField<FStructProperty>(Pin->GetClass()->FindPropertyByName(TEXT("Properties"))))
            {
                const void* Value = PinProps->ContainerPtrToValuePtr<void>(Pin);
                if (Value)
                {
                    Label = ExportStructFieldTextByName(PinProps->Struct, Value, TEXT("Label"), Pin);
                    AllowedTypes = ExportStructFieldTextByName(PinProps->Struct, Value, TEXT("AllowedTypes"), Pin);
                    Status = ExportStructFieldTextByName(PinProps->Struct, Value, TEXT("PinStatus"), Pin);
                    AllowMultiple = ExportStructFieldTextByName(PinProps->Struct, Value, TEXT("bAllowMultipleData"), Pin);
                    Invisible = ExportStructFieldTextByName(PinProps->Struct, Value, TEXT("bInvisiblePin"), Pin);
                }
            }
            const TSharedRef<FJsonObject> PinJson = MakeShared<FJsonObject>();
            PinJson->SetStringField(TEXT("pcg_path"), AssetPath);
            PinJson->SetStringField(TEXT("pin_id"), PinId);
            PinJson->SetStringField(TEXT("node_id"), Node ? Node->GetPathName() : TEXT(""));
            PinJson->SetStringField(TEXT("direction"), PinDirections.FindRef(PinId));
            PinJson->SetNumberField(TEXT("pin_index"), PinIndices.Contains(PinId) ? PinIndices.FindRef(PinId) : -1);
            PinJson->SetStringField(TEXT("label"), Label);
            PinJson->SetStringField(TEXT("allowed_types"), AllowedTypes);
            PinJson->SetStringField(TEXT("pin_status"), Status);
            PinJson->SetStringField(TEXT("allow_multiple_data"), AllowMultiple);
            PinJson->SetStringField(TEXT("invisible"), Invisible);
            PinJson->SetStringField(TEXT("raw_properties"), PropertiesRaw);
            if (!PinsWriter.Write(PinJson)) return false;
            ++Counts.PCGPins;
        }

        for (UObject* Edge : Edges)
        {
            UObject* SourcePin = GetReflectedObjectProperty(Edge, TEXT("InputPin"));
            UObject* TargetPin = GetReflectedObjectProperty(Edge, TEXT("OutputPin"));
            UObject* SourceNode = SourcePin ? GetReflectedObjectProperty(SourcePin, TEXT("Node")) : nullptr;
            UObject* TargetNode = TargetPin ? GetReflectedObjectProperty(TargetPin, TEXT("Node")) : nullptr;
            const TSharedRef<FJsonObject> EdgeJson = MakeShared<FJsonObject>();
            EdgeJson->SetStringField(TEXT("pcg_path"), AssetPath);
            EdgeJson->SetStringField(TEXT("edge_id"), Edge->GetPathName());
            EdgeJson->SetStringField(TEXT("source_pin_id"), SourcePin ? SourcePin->GetPathName() : TEXT(""));
            EdgeJson->SetStringField(TEXT("target_pin_id"), TargetPin ? TargetPin->GetPathName() : TEXT(""));
            EdgeJson->SetStringField(TEXT("source_node_id"), SourceNode ? SourceNode->GetPathName() : TEXT(""));
            EdgeJson->SetStringField(TEXT("target_node_id"), TargetNode ? TargetNode->GetPathName() : TEXT(""));
            if (!EdgesWriter.Write(EdgeJson)) return false;
            ++Counts.PCGEdges;
        }
        for (UObject* Embedded : EmbeddedGraphs)
        {
            if (!ScanPCGGraphAsset(Embedded, Embedded->GetPathName(), GraphsWriter, NodesWriter, PinsWriter, EdgesWriter, PropertiesWriter, Counts)) return false;
        }
        return true;
    }

    static bool IsExpressionInputStruct(const UScriptStruct* Struct)
    {
        if (!Struct) return false;
        for (const UStruct* Current = Struct; Current; Current = Current->GetSuperStruct())
        {
            const FString Name = Current->GetName();
            if (Name == TEXT("ExpressionInput") || Name.EndsWith(TEXT("MaterialInput")))
            {
                return true;
            }
        }
        return false;
    }

    static bool WriteMaterialInputEdge(
        UScriptStruct* Struct,
        const void* StructValue,
        UObject* Owner,
        const FString& AssetPath,
        const FString& TargetId,
        const FString& TargetInput,
        int32 InputIndex,
        FJsonlWriter& EdgesWriter,
        FScanCounts& Counts)
    {
        if (!Struct || !StructValue || !IsExpressionInputStruct(Struct))
        {
            return true;
        }
        UObject* Expression = GetStructObjectField(Struct, StructValue, TEXT("Expression"));
        if (!Expression)
        {
            return true;
        }
        const FString OutputIndex = ExportStructFieldTextByName(Struct, StructValue, TEXT("OutputIndex"), Owner);
        const FString InputName = ExportStructFieldTextByName(Struct, StructValue, TEXT("InputName"), Owner);
        const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
        Json->SetStringField(TEXT("material_path"), AssetPath);
        Json->SetStringField(TEXT("source_expression_id"), Expression->GetPathName());
        Json->SetStringField(TEXT("source_output_index"), OutputIndex);
        Json->SetStringField(TEXT("source_output_name"), InputName);
        Json->SetStringField(TEXT("target_expression_id"), TargetId);
        Json->SetStringField(TEXT("target_input_name"), TargetInput);
        Json->SetNumberField(TEXT("target_input_index"), InputIndex);
        Json->SetStringField(TEXT("edge_kind"), TargetId.StartsWith(TEXT("$output:")) ? TEXT("material_output") : TEXT("expression"));
        if (!EdgesWriter.Write(Json)) return false;
        ++Counts.MaterialEdges;
        return true;
    }

    static bool ScanMaterialInputValueRecursive(
        FProperty* Property,
        const void* Value,
        UObject* Owner,
        const FString& AssetPath,
        const FString& TargetId,
        const FString& PropertyPath,
        int32& InputIndex,
        int32 Depth,
        FJsonlWriter& EdgesWriter,
        FScanCounts& Counts)
    {
        if (!Property || !Value || Depth > 4)
        {
            return true;
        }
        if (FStructProperty* StructProperty = CastField<FStructProperty>(Property))
        {
            if (IsExpressionInputStruct(StructProperty->Struct))
            {
                return WriteMaterialInputEdge(
                    StructProperty->Struct,
                    Value,
                    Owner,
                    AssetPath,
                    TargetId,
                    PropertyPath,
                    InputIndex++,
                    EdgesWriter,
                    Counts);
            }
            if (!StructProperty->Struct)
            {
                return true;
            }
            for (TFieldIterator<FProperty> It(StructProperty->Struct, EFieldIterationFlags::Default); It; ++It)
            {
                FProperty* Child = *It;
                for (int32 ArrayIndex = 0; ArrayIndex < Child->ArrayDim; ++ArrayIndex)
                {
                    const void* ChildValue = Child->ContainerPtrToValuePtr<void>(Value, ArrayIndex);
                    FString ChildPath = PropertyPath + TEXT(".") + Child->GetName();
                    if (Child->ArrayDim > 1) ChildPath += FString::Printf(TEXT("[%d]"), ArrayIndex);
                    if (!ScanMaterialInputValueRecursive(Child, ChildValue, Owner, AssetPath, TargetId, ChildPath, InputIndex, Depth + 1, EdgesWriter, Counts)) return false;
                }
            }
        }
        else if (FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
        {
            if (!ArrayProperty->Inner) return true;
            FScriptArrayHelper Helper(ArrayProperty, Value);
            const int32 MaxElements = FMath::Min(Helper.Num(), 256);
            for (int32 Index = 0; Index < MaxElements; ++Index)
            {
                if (!ScanMaterialInputValueRecursive(
                        ArrayProperty->Inner,
                        Helper.GetRawPtr(Index),
                        Owner,
                        AssetPath,
                        TargetId,
                        FString::Printf(TEXT("%s[%d]"), *PropertyPath, Index),
                        InputIndex,
                        Depth + 1,
                        EdgesWriter,
                        Counts)) return false;
            }
        }
        return true;
    }

    static bool ScanMaterialExpressionInputs(
        UObject* Expression,
        const FString& AssetPath,
        FJsonlWriter& EdgesWriter,
        FScanCounts& Counts)
    {
        if (!Expression) return true;
        int32 InputIndex = 0;
        for (UClass* Class = Expression->GetClass(); Class && Class != UObject::StaticClass(); Class = Class->GetSuperClass())
        {
            for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
            {
                FProperty* Property = *It;
                for (int32 ArrayIndex = 0; ArrayIndex < Property->ArrayDim; ++ArrayIndex)
                {
                    const void* Value = Property->ContainerPtrToValuePtr<void>(Expression, ArrayIndex);
                    FString PropertyPath = Property->GetName();
                    if (Property->ArrayDim > 1) PropertyPath += FString::Printf(TEXT("[%d]"), ArrayIndex);
                    if (!ScanMaterialInputValueRecursive(Property, Value, Expression, AssetPath, Expression->GetPathName(), PropertyPath, InputIndex, 0, EdgesWriter, Counts)) return false;
                }
            }
        }
        return true;
    }

    static bool ScanMaterialAsset(
        UObject* MaterialAsset,
        const FString& AssetPath,
        const FString& AssetKind,
        FJsonlWriter& MaterialsWriter,
        FJsonlWriter& ExpressionsWriter,
        FJsonlWriter& EdgesWriter,
        FJsonlWriter& PropertiesWriter,
        FScanCounts& Counts)
    {
        if (!MaterialAsset) return true;
        TArray<UObject*> OwnedObjects;
        GetObjectsWithOuter(MaterialAsset, OwnedObjects, EGetObjectsFlags::IncludeNestedObjects);
        OwnedObjects.Sort([](const UObject& A, const UObject& B) { return A.GetPathName() < B.GetPathName(); });
        TArray<UObject*> Expressions;
        TArray<UObject*> EditorDataObjects;
        for (UObject* Object : OwnedObjects)
        {
            if (!Object) continue;
            if (ClassIsOrDerivedFromName(Object->GetClass(), TEXT("MaterialExpression"))) Expressions.Add(Object);
            if (Object->GetClass()->GetName().Contains(TEXT("MaterialEditorOnlyData")) || Object->GetClass()->GetName().Contains(TEXT("MaterialFunctionEditorOnlyData"))) EditorDataObjects.Add(Object);
        }

        const TSharedRef<FJsonObject> AssetJson = MakeShared<FJsonObject>();
        AssetJson->SetStringField(TEXT("material_path"), AssetPath);
        AssetJson->SetStringField(TEXT("material_kind"), AssetKind);
        AssetJson->SetStringField(TEXT("class_path"), MaterialAsset->GetClass()->GetPathName());
        AssetJson->SetNumberField(TEXT("expression_count"), Expressions.Num());
        UObject* Parent = GetReflectedObjectProperty(MaterialAsset, TEXT("Parent"));
        AssetJson->SetStringField(TEXT("parent_path"), Parent ? Parent->GetPathName() : TEXT(""));
        AssetJson->SetStringField(TEXT("material_domain"), ExportObjectPropertyByName(MaterialAsset, TEXT("MaterialDomain")));
        AssetJson->SetStringField(TEXT("blend_mode"), ExportObjectPropertyByName(MaterialAsset, TEXT("BlendMode")));
        AssetJson->SetStringField(TEXT("shading_model"), ExportObjectPropertyByName(MaterialAsset, TEXT("ShadingModel")));
        if (!MaterialsWriter.Write(AssetJson)) return false;
        ++Counts.Materials;
        if (!ScanVisualObjectProperties(MaterialAsset, AssetPath, TEXT("material"), AssetKind, AssetPath, PropertiesWriter, Counts.MaterialProperties)) return false;

        for (UObject* Expression : Expressions)
        {
            const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
            Json->SetStringField(TEXT("material_path"), AssetPath);
            Json->SetStringField(TEXT("expression_id"), Expression->GetPathName());
            Json->SetStringField(TEXT("expression_class"), Expression->GetClass()->GetPathName());
            Json->SetStringField(TEXT("expression_name"), Expression->GetName());
            Json->SetStringField(TEXT("editor_x"), ExportObjectPropertyByName(Expression, TEXT("MaterialExpressionEditorX")));
            Json->SetStringField(TEXT("editor_y"), ExportObjectPropertyByName(Expression, TEXT("MaterialExpressionEditorY")));
            Json->SetStringField(TEXT("description"), ExportObjectPropertyByName(Expression, TEXT("Desc")));
            Json->SetStringField(TEXT("parameter_name"), ExportObjectPropertyByName(Expression, TEXT("ParameterName")));
            UObject* Function = GetReflectedObjectProperty(Expression, TEXT("MaterialFunction"));
            Json->SetStringField(TEXT("function_path"), Function ? Function->GetPathName() : TEXT(""));
            UObject* Texture = GetReflectedObjectProperty(Expression, TEXT("Texture"));
            Json->SetStringField(TEXT("texture_path"), Texture ? Texture->GetPathName() : TEXT(""));
            Json->SetStringField(TEXT("default_value"), ExportObjectPropertyByName(Expression, TEXT("DefaultValue"), 32768));
            Json->SetStringField(TEXT("value"), ExportObjectPropertyByName(Expression, TEXT("Value"), 32768));
            if (!ExpressionsWriter.Write(Json)) return false;
            ++Counts.MaterialExpressions;
            if (!ScanVisualObjectProperties(Expression, AssetPath, TEXT("material"), TEXT("expression"), Expression->GetPathName(), PropertiesWriter, Counts.MaterialProperties)) return false;
            if (!ScanMaterialExpressionInputs(Expression, AssetPath, EdgesWriter, Counts)) return false;
        }

        for (UObject* EditorData : EditorDataObjects)
        {
            if (!EditorData) continue;
            for (UClass* Class = EditorData->GetClass(); Class && Class != UObject::StaticClass(); Class = Class->GetSuperClass())
            {
                for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
                {
                    FStructProperty* StructProperty = CastField<FStructProperty>(*It);
                    if (!StructProperty || !IsExpressionInputStruct(StructProperty->Struct)) continue;
                    const void* Value = StructProperty->ContainerPtrToValuePtr<void>(EditorData);
                    if (!WriteMaterialInputEdge(StructProperty->Struct, Value, EditorData, AssetPath, TEXT("$output:") + StructProperty->GetName(), StructProperty->GetName(), 0, EdgesWriter, Counts)) return false;
                }
            }
            if (!ScanVisualObjectProperties(EditorData, AssetPath, TEXT("material"), TEXT("editor_data"), EditorData->GetPathName(), PropertiesWriter, Counts.MaterialProperties)) return false;
        }
        return true;
    }

    static bool ScanAssets(
        const FString& ProjectDir,
        const FString& ToolPluginDir,
        bool bIncludeEngine,
        bool bIncludeSelf,
        FJsonlWriter& AssetsWriter,
        FJsonlWriter& DependenciesWriter,
        FJsonlWriter& BlueprintsWriter,
        FJsonlWriter& GraphsWriter,
        FJsonlWriter& NodesWriter,
        FJsonlWriter& PinsWriter,
        FJsonlWriter& PropertiesWriter,
        FJsonlWriter& ReferencesWriter,
        FJsonlWriter& BindingsWriter,
        FJsonlWriter& InterfacesWriter,
        FJsonlWriter& DefaultsWriter,
        FJsonlWriter& ComponentPropertiesWriter,
        FJsonlWriter& StateValuesWriter,
        FJsonlWriter& TimelinesWriter,
        FJsonlWriter& TimelineTracksWriter,
        FJsonlWriter& TimelineKeysWriter,
        FJsonlWriter& WidgetsWriter,
        FJsonlWriter& WidgetPropertiesWriter,
        FJsonlWriter& WidgetBindingsWriter,
        FJsonlWriter& WidgetAnimationsWriter,
        FJsonlWriter& WidgetAnimationBindingsWriter,
        FJsonlWriter& RigVMObjectsWriter,
        FJsonlWriter& RigVMPinsWriter,
        FJsonlWriter& RigVMLinksWriter,
        FJsonlWriter& RigVMPropertiesWriter,
        FJsonlWriter& RigVMReferencesWriter,
        FJsonlWriter& EdgesWriter,
        FJsonlWriter& BehaviorTreesWriter,
        FJsonlWriter& BehaviorTreeNodesWriter,
        FJsonlWriter& BehaviorTreeEdgesWriter,
        FJsonlWriter& BlackboardsWriter,
        FJsonlWriter& BlackboardKeysWriter,
        FJsonlWriter& EQSQueriesWriter,
        FJsonlWriter& EQSOptionsWriter,
        FJsonlWriter& EQSGeneratorsWriter,
        FJsonlWriter& EQSTestsWriter,
        FJsonlWriter& StateTreesWriter,
        FJsonlWriter& StateTreeStatesWriter,
        FJsonlWriter& StateTreeNodesWriter,
        FJsonlWriter& StateTreeTransitionsWriter,
        FJsonlWriter& StateTreeBindingsWriter,
        FJsonlWriter& AIPropertiesWriter,
        FJsonlWriter& PCGGraphsWriter,
        FJsonlWriter& PCGNodesWriter,
        FJsonlWriter& PCGPinsWriter,
        FJsonlWriter& PCGEdgesWriter,
        FJsonlWriter& PCGPropertiesWriter,
        FJsonlWriter& MaterialsWriter,
        FJsonlWriter& MaterialExpressionsWriter,
        FJsonlWriter& MaterialEdgesWriter,
        FJsonlWriter& MaterialPropertiesWriter,
        bool bIncludeRawRigVMProperties,
        FScanCounts& Counts)
    {
        FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
        IAssetRegistry& Registry = AssetRegistryModule.Get();

        TArray<FAssetData> Assets;
        Registry.GetAllAssets(Assets, true);
        Assets.Sort([](const FAssetData& A, const FAssetData& B)
        {
            return A.GetSoftObjectPath().ToString() < B.GetSoftObjectPath().ToString();
        });

        for (const FAssetData& Asset : Assets)
        {
            FString PackageFilename;
            const bool bHasDiskPackage = FPackageName::DoesPackageExist(Asset.PackageName.ToString(), &PackageFilename, false);

            if (!bIncludeSelf && bHasDiskPackage && !ToolPluginDir.IsEmpty() && IsInsideDirectory(PackageFilename, ToolPluginDir))
            {
                continue;
            }

            if (!bIncludeEngine)
            {
                if (!bHasDiskPackage || !IsInsideDirectory(PackageFilename, ProjectDir))
                {
                    continue;
                }
            }

            const FString ObjectPath = Asset.GetSoftObjectPath().ToString();
            const TSharedRef<FJsonObject> AssetJson = MakeShared<FJsonObject>();
            AssetJson->SetStringField(TEXT("object_path"), ObjectPath);
            AssetJson->SetStringField(TEXT("asset_name"), Asset.AssetName.ToString());
            AssetJson->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
            AssetJson->SetStringField(TEXT("package_path"), Asset.PackagePath.ToString());
            AssetJson->SetStringField(TEXT("class_path"), Asset.AssetClassPath.ToString());
            AssetJson->SetStringField(TEXT("disk_path"), bHasDiskPackage ? NormalizeAbsolutePath(PackageFilename) : TEXT(""));

            const TSharedRef<FJsonObject> TagsJson = MakeShared<FJsonObject>();
            for (const TPair<FName, FAssetTagValueRef> Tag : Asset.TagsAndValues)
            {
                TagsJson->SetStringField(Tag.Key.ToString(), Tag.Value.AsString());
            }
            AssetJson->SetObjectField(TEXT("tags"), TagsJson);

            TArray<FName> Dependencies;
            Registry.GetDependencies(
                Asset.PackageName,
                Dependencies,
                UE::AssetRegistry::EDependencyCategory::Package,
                UE::AssetRegistry::FDependencyQuery());
            Dependencies.Sort([](const FName& A, const FName& B) { return A.LexicalLess(B); });

            TArray<TSharedPtr<FJsonValue>> DependencyArray;
            for (const FName Dependency : Dependencies)
            {
                DependencyArray.Add(MakeShared<FJsonValueString>(Dependency.ToString()));

                const TSharedRef<FJsonObject> DependencyJson = MakeShared<FJsonObject>();
                DependencyJson->SetStringField(TEXT("source_package"), Asset.PackageName.ToString());
                DependencyJson->SetStringField(TEXT("target_package"), Dependency.ToString());
                DependencyJson->SetStringField(TEXT("category"), TEXT("package"));
                if (!DependenciesWriter.Write(DependencyJson))
                {
                    return false;
                }
                ++Counts.AssetDependencies;
            }
            AssetJson->SetArrayField(TEXT("dependencies"), DependencyArray);

            if (!AssetsWriter.Write(AssetJson))
            {
                return false;
            }
            ++Counts.Assets;

            const FString AssetClassPath = Asset.AssetClassPath.ToString();
            if (AssetClassPath == TEXT("/Script/PCG.PCGGraph"))
            {
                if (UObject* PCGAsset = Asset.GetAsset())
                {
                    if (!ScanPCGGraphAsset(PCGAsset, ObjectPath, PCGGraphsWriter, PCGNodesWriter, PCGPinsWriter, PCGEdgesWriter, PCGPropertiesWriter, Counts)) return false;
                }
            }
            else if (AssetClassPath == TEXT("/Script/Engine.Material") ||
                     AssetClassPath == TEXT("/Script/Engine.MaterialFunction") ||
                     AssetClassPath == TEXT("/Script/Engine.MaterialInstanceConstant") ||
                     AssetClassPath == TEXT("/Script/Engine.MaterialFunctionInstance"))
            {
                if (UObject* MaterialAsset = Asset.GetAsset())
                {
                    FString Kind = TEXT("material");
                    if (AssetClassPath.Contains(TEXT("MaterialFunctionInstance"))) Kind = TEXT("function_instance");
                    else if (AssetClassPath.Contains(TEXT("MaterialFunction"))) Kind = TEXT("function");
                    else if (AssetClassPath.Contains(TEXT("MaterialInstance"))) Kind = TEXT("instance");
                    if (!ScanMaterialAsset(MaterialAsset, ObjectPath, Kind, MaterialsWriter, MaterialExpressionsWriter, MaterialEdgesWriter, MaterialPropertiesWriter, Counts)) return false;
                }
            }

            if (AssetClassPath == TEXT("/Script/AIModule.BehaviorTree") ||
                AssetClassPath == TEXT("/Script/AIModule.BlackboardData") ||
                AssetClassPath == TEXT("/Script/AIModule.EnvQuery") ||
                AssetClassPath == TEXT("/Script/StateTreeModule.StateTree"))
            {
                if (UObject* AIAsset = Asset.GetAsset())
                {
                    if (AssetClassPath == TEXT("/Script/AIModule.BehaviorTree"))
                    {
                        if (!ScanBehaviorTreeAsset(AIAsset, ObjectPath, BehaviorTreesWriter, BehaviorTreeNodesWriter, BehaviorTreeEdgesWriter, AIPropertiesWriter, Counts)) return false;
                    }
                    else if (AssetClassPath == TEXT("/Script/AIModule.BlackboardData"))
                    {
                        if (!ScanBlackboardAsset(AIAsset, ObjectPath, BlackboardsWriter, BlackboardKeysWriter, AIPropertiesWriter, Counts)) return false;
                    }
                    else if (AssetClassPath == TEXT("/Script/AIModule.EnvQuery"))
                    {
                        if (!ScanEQSAsset(AIAsset, ObjectPath, EQSQueriesWriter, EQSOptionsWriter, EQSGeneratorsWriter, EQSTestsWriter, AIPropertiesWriter, Counts)) return false;
                    }
                    else if (AssetClassPath == TEXT("/Script/StateTreeModule.StateTree"))
                    {
                        if (!ScanStateTreeAsset(AIAsset, ObjectPath, StateTreesWriter, StateTreeStatesWriter, StateTreeNodesWriter, StateTreeTransitionsWriter, StateTreeBindingsWriter, AIPropertiesWriter, Counts)) return false;
                    }
                }
            }

            if (AssetClassPath.Contains(TEXT("Blueprint"), ESearchCase::CaseSensitive))
            {
                if (UBlueprint* Blueprint = Cast<UBlueprint>(Asset.GetAsset()))
                {
                    if (!ScanBlueprint(
                            Blueprint,
                            ObjectPath,
                            BlueprintsWriter,
                            GraphsWriter,
                            NodesWriter,
                            PinsWriter,
                            PropertiesWriter,
                            ReferencesWriter,
                            BindingsWriter,
                            InterfacesWriter,
                            DefaultsWriter,
                            ComponentPropertiesWriter,
                            StateValuesWriter,
                            TimelinesWriter,
                            TimelineTracksWriter,
                            TimelineKeysWriter,
                            WidgetsWriter,
                            WidgetPropertiesWriter,
                            WidgetBindingsWriter,
                            WidgetAnimationsWriter,
                            WidgetAnimationBindingsWriter,
                            RigVMObjectsWriter,
                            RigVMPinsWriter,
                            RigVMLinksWriter,
                            RigVMPropertiesWriter,
                            RigVMReferencesWriter,
                            EdgesWriter,
                            bIncludeRawRigVMProperties,
                            Counts))
                    {
                        return false;
                    }
                }
            }
        }
        return true;
    }
}

UUnrealAssetToolCommandlet::UUnrealAssetToolCommandlet()
{
    IsClient = false;
    IsEditor = true;
    IsServer = false;
    LogToConsole = true;
    ShowErrorCount = true;
    UseCommandletResultAsExitCode = true;
    HelpDescription = TEXT("Indexes an Unreal project into AI-friendly JSONL records.");
    HelpUsage = TEXT("UnrealEditor-Cmd.exe Project.uproject -run=UnrealAssetTool -Output=<dir> [-NativeOnly] [-IncludeGenerated] [-IncludeEngine] [-IncludeSelf] [-IncludeRawRigVMProperties]");
}

int32 UUnrealAssetToolCommandlet::Main(const FString& Params)
{
    using namespace UnrealAssetTool;

    UE_LOG(LogTemp, Display, TEXT("UnrealAssetTool: commandlet starting."));

    FString OutputDir;
    FParse::Value(*Params, TEXT("Output="), OutputDir);
    const bool bNativeOnly = FParse::Param(*Params, TEXT("NativeOnly"));
    const bool bIncludeGenerated = FParse::Param(*Params, TEXT("IncludeGenerated"));
    const bool bIncludeEngine = FParse::Param(*Params, TEXT("IncludeEngine"));
    const bool bIncludeSelf = FParse::Param(*Params, TEXT("IncludeSelf"));
    const bool bIncludeRawRigVMProperties = FParse::Param(*Params, TEXT("IncludeRawRigVMProperties"));

    const FString ProjectDir = NormalizeAbsolutePath(FPaths::ProjectDir());
    if (OutputDir.IsEmpty())
    {
        OutputDir = FPaths::Combine(ProjectDir, TEXT(".uatool"));
    }
    else if (FPaths::IsRelative(OutputDir))
    {
        OutputDir = FPaths::Combine(ProjectDir, OutputDir);
    }
    OutputDir = NormalizeAbsolutePath(OutputDir);

    FString ToolPluginDir;
    const TSharedPtr<IPlugin> ToolPlugin = IPluginManager::Get().FindPlugin(TEXT("UnrealAssetTool"));
    if (ToolPlugin.IsValid())
    {
        ToolPluginDir = NormalizeAbsolutePath(ToolPlugin->GetBaseDir());
    }
    else
    {
        UE_LOG(LogTemp, Warning,
            TEXT("UnrealAssetTool: could not resolve its plugin root; self-exclusion will only affect the output directory."));
    }

    IFileManager::Get().MakeDirectory(*OutputDir, true);

    if (bNativeOnly)
    {
        FString NativeError;
        if (!UnrealAssetToolNative::Scan(ProjectDir, ToolPluginDir, OutputDir, NativeError))
        {
            UE_LOG(LogTemp, Error, TEXT("UnrealAssetTool: native-only C++ scan failed: %s"), *NativeError);
            return 6;
        }
        UE_LOG(LogTemp, Display, TEXT("UnrealAssetTool: native-only capture complete: %s"), *OutputDir);
        return 0;
    }

    FJsonlWriter FilesWriter(FPaths::Combine(OutputDir, TEXT("files.jsonl")));
    FJsonlWriter SourceWriter(FPaths::Combine(OutputDir, TEXT("source_chunks.jsonl")));
    FJsonlWriter AssetsWriter(FPaths::Combine(OutputDir, TEXT("assets.jsonl")));
    FJsonlWriter DependenciesWriter(FPaths::Combine(OutputDir, TEXT("asset_dependencies.jsonl")));
    FJsonlWriter BlueprintsWriter(FPaths::Combine(OutputDir, TEXT("blueprints.jsonl")));
    FJsonlWriter GraphsWriter(FPaths::Combine(OutputDir, TEXT("blueprint_graphs.jsonl")));
    FJsonlWriter NodesWriter(FPaths::Combine(OutputDir, TEXT("blueprint_nodes.jsonl")));
    FJsonlWriter PinsWriter(FPaths::Combine(OutputDir, TEXT("blueprint_pins.jsonl")));
    FJsonlWriter PropertiesWriter(FPaths::Combine(OutputDir, TEXT("blueprint_node_properties.jsonl")));
    FJsonlWriter ReferencesWriter(FPaths::Combine(OutputDir, TEXT("blueprint_node_references.jsonl")));
    FJsonlWriter BindingsWriter(FPaths::Combine(OutputDir, TEXT("blueprint_bindings.jsonl")));
    FJsonlWriter InterfacesWriter(FPaths::Combine(OutputDir, TEXT("blueprint_interfaces.jsonl")));
    FJsonlWriter DefaultsWriter(FPaths::Combine(OutputDir, TEXT("blueprint_defaults.jsonl")));
    FJsonlWriter ComponentPropertiesWriter(FPaths::Combine(OutputDir, TEXT("blueprint_component_properties.jsonl")));
    FJsonlWriter StateValuesWriter(FPaths::Combine(OutputDir, TEXT("blueprint_state_values.jsonl")));
    FJsonlWriter TimelinesWriter(FPaths::Combine(OutputDir, TEXT("blueprint_timelines.jsonl")));
    FJsonlWriter TimelineTracksWriter(FPaths::Combine(OutputDir, TEXT("blueprint_timeline_tracks.jsonl")));
    FJsonlWriter TimelineKeysWriter(FPaths::Combine(OutputDir, TEXT("blueprint_timeline_keys.jsonl")));
    FJsonlWriter WidgetsWriter(FPaths::Combine(OutputDir, TEXT("blueprint_widgets.jsonl")));
    FJsonlWriter WidgetPropertiesWriter(FPaths::Combine(OutputDir, TEXT("blueprint_widget_properties.jsonl")));
    FJsonlWriter WidgetBindingsWriter(FPaths::Combine(OutputDir, TEXT("blueprint_widget_bindings.jsonl")));
    FJsonlWriter WidgetAnimationsWriter(FPaths::Combine(OutputDir, TEXT("blueprint_widget_animations.jsonl")));
    FJsonlWriter WidgetAnimationBindingsWriter(FPaths::Combine(OutputDir, TEXT("blueprint_widget_animation_bindings.jsonl")));
    FJsonlWriter RigVMObjectsWriter(FPaths::Combine(OutputDir, TEXT("rigvm_objects.jsonl")));
    FJsonlWriter RigVMPinsWriter(FPaths::Combine(OutputDir, TEXT("rigvm_pins.jsonl")));
    FJsonlWriter RigVMLinksWriter(FPaths::Combine(OutputDir, TEXT("rigvm_links.jsonl")));
    FJsonlWriter RigVMPropertiesWriter(FPaths::Combine(OutputDir, TEXT("rigvm_properties.jsonl")));
    FJsonlWriter RigVMReferencesWriter(FPaths::Combine(OutputDir, TEXT("rigvm_references.jsonl")));
    FJsonlWriter EdgesWriter(FPaths::Combine(OutputDir, TEXT("blueprint_edges.jsonl")));
    FJsonlWriter BehaviorTreesWriter(FPaths::Combine(OutputDir, TEXT("behavior_trees.jsonl")));
    FJsonlWriter BehaviorTreeNodesWriter(FPaths::Combine(OutputDir, TEXT("behavior_tree_nodes.jsonl")));
    FJsonlWriter BehaviorTreeEdgesWriter(FPaths::Combine(OutputDir, TEXT("behavior_tree_edges.jsonl")));
    FJsonlWriter BlackboardsWriter(FPaths::Combine(OutputDir, TEXT("blackboards.jsonl")));
    FJsonlWriter BlackboardKeysWriter(FPaths::Combine(OutputDir, TEXT("blackboard_keys.jsonl")));
    FJsonlWriter EQSQueriesWriter(FPaths::Combine(OutputDir, TEXT("eqs_queries.jsonl")));
    FJsonlWriter EQSOptionsWriter(FPaths::Combine(OutputDir, TEXT("eqs_options.jsonl")));
    FJsonlWriter EQSGeneratorsWriter(FPaths::Combine(OutputDir, TEXT("eqs_generators.jsonl")));
    FJsonlWriter EQSTestsWriter(FPaths::Combine(OutputDir, TEXT("eqs_tests.jsonl")));
    FJsonlWriter StateTreesWriter(FPaths::Combine(OutputDir, TEXT("statetrees.jsonl")));
    FJsonlWriter StateTreeStatesWriter(FPaths::Combine(OutputDir, TEXT("statetree_states.jsonl")));
    FJsonlWriter StateTreeNodesWriter(FPaths::Combine(OutputDir, TEXT("statetree_nodes.jsonl")));
    FJsonlWriter StateTreeTransitionsWriter(FPaths::Combine(OutputDir, TEXT("statetree_transitions.jsonl")));
    FJsonlWriter StateTreeBindingsWriter(FPaths::Combine(OutputDir, TEXT("statetree_bindings.jsonl")));
    FJsonlWriter AIPropertiesWriter(FPaths::Combine(OutputDir, TEXT("ai_properties.jsonl")));
    FJsonlWriter PCGGraphsWriter(FPaths::Combine(OutputDir, TEXT("pcg_graphs.jsonl")));
    FJsonlWriter PCGNodesWriter(FPaths::Combine(OutputDir, TEXT("pcg_nodes.jsonl")));
    FJsonlWriter PCGPinsWriter(FPaths::Combine(OutputDir, TEXT("pcg_pins.jsonl")));
    FJsonlWriter PCGEdgesWriter(FPaths::Combine(OutputDir, TEXT("pcg_edges.jsonl")));
    FJsonlWriter PCGPropertiesWriter(FPaths::Combine(OutputDir, TEXT("pcg_properties.jsonl")));
    FJsonlWriter MaterialsWriter(FPaths::Combine(OutputDir, TEXT("materials.jsonl")));
    FJsonlWriter MaterialExpressionsWriter(FPaths::Combine(OutputDir, TEXT("material_expressions.jsonl")));
    FJsonlWriter MaterialEdgesWriter(FPaths::Combine(OutputDir, TEXT("material_edges.jsonl")));
    FJsonlWriter MaterialPropertiesWriter(FPaths::Combine(OutputDir, TEXT("material_properties.jsonl")));

    if (!FilesWriter.IsValid() || !SourceWriter.IsValid() || !AssetsWriter.IsValid() ||
        !DependenciesWriter.IsValid() || !BlueprintsWriter.IsValid() || !GraphsWriter.IsValid() ||
        !NodesWriter.IsValid() || !PinsWriter.IsValid() || !PropertiesWriter.IsValid() ||
        !ReferencesWriter.IsValid() || !BindingsWriter.IsValid() || !InterfacesWriter.IsValid() ||
        !DefaultsWriter.IsValid() || !ComponentPropertiesWriter.IsValid() || !StateValuesWriter.IsValid() ||
        !TimelinesWriter.IsValid() || !TimelineTracksWriter.IsValid() || !TimelineKeysWriter.IsValid() ||
        !WidgetsWriter.IsValid() || !WidgetPropertiesWriter.IsValid() || !WidgetBindingsWriter.IsValid() ||
        !WidgetAnimationsWriter.IsValid() || !WidgetAnimationBindingsWriter.IsValid() ||
        !RigVMObjectsWriter.IsValid() || !RigVMPinsWriter.IsValid() || !RigVMLinksWriter.IsValid() ||
        !RigVMPropertiesWriter.IsValid() || !RigVMReferencesWriter.IsValid() ||
        !EdgesWriter.IsValid() || !BehaviorTreesWriter.IsValid() || !BehaviorTreeNodesWriter.IsValid() ||
        !BehaviorTreeEdgesWriter.IsValid() || !BlackboardsWriter.IsValid() || !BlackboardKeysWriter.IsValid() ||
        !EQSQueriesWriter.IsValid() || !EQSOptionsWriter.IsValid() || !EQSGeneratorsWriter.IsValid() ||
        !EQSTestsWriter.IsValid() || !StateTreesWriter.IsValid() || !StateTreeStatesWriter.IsValid() ||
        !StateTreeNodesWriter.IsValid() || !StateTreeTransitionsWriter.IsValid() || !StateTreeBindingsWriter.IsValid() ||
        !AIPropertiesWriter.IsValid() || !PCGGraphsWriter.IsValid() || !PCGNodesWriter.IsValid() ||
        !PCGPinsWriter.IsValid() || !PCGEdgesWriter.IsValid() || !PCGPropertiesWriter.IsValid() ||
        !MaterialsWriter.IsValid() || !MaterialExpressionsWriter.IsValid() || !MaterialEdgesWriter.IsValid() ||
        !MaterialPropertiesWriter.IsValid())
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetTool: could not create one or more output files under %s"), *OutputDir);
        return 2;
    }

    FScanCounts Counts;
    if (!ScanFiles(ProjectDir, ToolPluginDir, OutputDir, bIncludeGenerated, bIncludeSelf, FilesWriter, SourceWriter, Counts))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetTool: file scan failed."));
        return 3;
    }

    if (!ScanAssets(
            ProjectDir,
            ToolPluginDir,
            bIncludeEngine,
            bIncludeSelf,
            AssetsWriter,
            DependenciesWriter,
            BlueprintsWriter,
            GraphsWriter,
            NodesWriter,
            PinsWriter,
            PropertiesWriter,
            ReferencesWriter,
            BindingsWriter,
            InterfacesWriter,
            DefaultsWriter,
            ComponentPropertiesWriter,
            StateValuesWriter,
            TimelinesWriter,
            TimelineTracksWriter,
            TimelineKeysWriter,
            WidgetsWriter,
            WidgetPropertiesWriter,
            WidgetBindingsWriter,
            WidgetAnimationsWriter,
            WidgetAnimationBindingsWriter,
            RigVMObjectsWriter,
            RigVMPinsWriter,
            RigVMLinksWriter,
            RigVMPropertiesWriter,
            RigVMReferencesWriter,
            EdgesWriter,
            BehaviorTreesWriter,
            BehaviorTreeNodesWriter,
            BehaviorTreeEdgesWriter,
            BlackboardsWriter,
            BlackboardKeysWriter,
            EQSQueriesWriter,
            EQSOptionsWriter,
            EQSGeneratorsWriter,
            EQSTestsWriter,
            StateTreesWriter,
            StateTreeStatesWriter,
            StateTreeNodesWriter,
            StateTreeTransitionsWriter,
            StateTreeBindingsWriter,
            AIPropertiesWriter,
            PCGGraphsWriter,
            PCGNodesWriter,
            PCGPinsWriter,
            PCGEdgesWriter,
            PCGPropertiesWriter,
            MaterialsWriter,
            MaterialExpressionsWriter,
            MaterialEdgesWriter,
            MaterialPropertiesWriter,
            bIncludeRawRigVMProperties,
            Counts))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetTool: asset scan failed."));
        return 4;
    }

    FString NativeError;
    if (!UnrealAssetToolNative::Scan(ProjectDir, ToolPluginDir, OutputDir, NativeError))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetTool: native C++ scan failed: %s"), *NativeError);
        return 6;
    }

    const TSharedRef<FJsonObject> Manifest = MakeShared<FJsonObject>();
    Manifest->SetNumberField(TEXT("schema_version"), SchemaVersion);
    Manifest->SetStringField(TEXT("tool"), TEXT("UnrealAssetTool"));
    Manifest->SetStringField(TEXT("generated_utc"), FDateTime::UtcNow().ToIso8601());
    Manifest->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Manifest->SetStringField(TEXT("project_file"), NormalizeAbsolutePath(FPaths::GetProjectFilePath()));
    Manifest->SetStringField(TEXT("project_dir"), ProjectDir);
    Manifest->SetStringField(TEXT("output_dir"), OutputDir);
    Manifest->SetStringField(TEXT("tool_plugin_dir"), ToolPluginDir);
    Manifest->SetBoolField(TEXT("include_generated"), bIncludeGenerated);
    Manifest->SetBoolField(TEXT("include_engine"), bIncludeEngine);
    Manifest->SetBoolField(TEXT("include_self"), bIncludeSelf);
    Manifest->SetBoolField(TEXT("include_raw_rigvm_properties"), bIncludeRawRigVMProperties);
    Manifest->SetNumberField(TEXT("native_schema_version"), UnrealAssetToolNative::SchemaVersion);

    const TSharedRef<FJsonObject> CountsJson = MakeShared<FJsonObject>();
    CountsJson->SetNumberField(TEXT("files"), static_cast<double>(Counts.Files));
    CountsJson->SetNumberField(TEXT("source_chunks"), static_cast<double>(Counts.SourceChunks));
    CountsJson->SetNumberField(TEXT("assets"), static_cast<double>(Counts.Assets));
    CountsJson->SetNumberField(TEXT("asset_dependencies"), static_cast<double>(Counts.AssetDependencies));
    CountsJson->SetNumberField(TEXT("blueprints"), static_cast<double>(Counts.Blueprints));
    CountsJson->SetNumberField(TEXT("blueprint_graphs"), static_cast<double>(Counts.BlueprintGraphs));
    CountsJson->SetNumberField(TEXT("blueprint_nodes"), static_cast<double>(Counts.BlueprintNodes));
    CountsJson->SetNumberField(TEXT("blueprint_pins"), static_cast<double>(Counts.BlueprintPins));
    CountsJson->SetNumberField(TEXT("blueprint_semantic_nodes"), static_cast<double>(Counts.BlueprintSemanticNodes));
    CountsJson->SetNumberField(TEXT("blueprint_node_properties"), static_cast<double>(Counts.BlueprintNodeProperties));
    CountsJson->SetNumberField(TEXT("blueprint_node_references"), static_cast<double>(Counts.BlueprintNodeReferences));
    CountsJson->SetNumberField(TEXT("blueprint_bindings"), static_cast<double>(Counts.BlueprintBindings));
    CountsJson->SetNumberField(TEXT("blueprint_interfaces"), static_cast<double>(Counts.BlueprintInterfaces));
    CountsJson->SetNumberField(TEXT("rigvm_objects"), static_cast<double>(Counts.RigVMObjects));
    CountsJson->SetNumberField(TEXT("rigvm_pins"), static_cast<double>(Counts.RigVMPins));
    CountsJson->SetNumberField(TEXT("rigvm_links"), static_cast<double>(Counts.RigVMLinks));
    CountsJson->SetNumberField(TEXT("rigvm_properties"), static_cast<double>(Counts.RigVMProperties));
    CountsJson->SetNumberField(TEXT("rigvm_references"), static_cast<double>(Counts.RigVMReferences));
    CountsJson->SetNumberField(TEXT("blueprint_edges"), static_cast<double>(Counts.BlueprintEdges));
    CountsJson->SetNumberField(TEXT("blueprint_variables"), static_cast<double>(Counts.BlueprintVariables));
    CountsJson->SetNumberField(TEXT("blueprint_components"), static_cast<double>(Counts.BlueprintComponents));
    CountsJson->SetNumberField(TEXT("blueprint_defaults"), static_cast<double>(Counts.BlueprintDefaults));
    CountsJson->SetNumberField(TEXT("blueprint_component_properties"), static_cast<double>(Counts.BlueprintComponentProperties));
    CountsJson->SetNumberField(TEXT("blueprint_state_values"), static_cast<double>(Counts.BlueprintStateValues));
    CountsJson->SetNumberField(TEXT("blueprint_timelines"), static_cast<double>(Counts.BlueprintTimelines));
    CountsJson->SetNumberField(TEXT("blueprint_timeline_tracks"), static_cast<double>(Counts.BlueprintTimelineTracks));
    CountsJson->SetNumberField(TEXT("blueprint_timeline_keys"), static_cast<double>(Counts.BlueprintTimelineKeys));
    CountsJson->SetNumberField(TEXT("blueprint_widgets"), static_cast<double>(Counts.BlueprintWidgets));
    CountsJson->SetNumberField(TEXT("blueprint_widget_properties"), static_cast<double>(Counts.BlueprintWidgetProperties));
    CountsJson->SetNumberField(TEXT("blueprint_widget_bindings"), static_cast<double>(Counts.BlueprintWidgetBindings));
    CountsJson->SetNumberField(TEXT("blueprint_widget_animations"), static_cast<double>(Counts.BlueprintWidgetAnimations));
    CountsJson->SetNumberField(TEXT("blueprint_widget_animation_bindings"), static_cast<double>(Counts.BlueprintWidgetAnimationBindings));
    CountsJson->SetNumberField(TEXT("behavior_trees"), static_cast<double>(Counts.BehaviorTrees));
    CountsJson->SetNumberField(TEXT("behavior_tree_nodes"), static_cast<double>(Counts.BehaviorTreeNodes));
    CountsJson->SetNumberField(TEXT("behavior_tree_edges"), static_cast<double>(Counts.BehaviorTreeEdges));
    CountsJson->SetNumberField(TEXT("blackboards"), static_cast<double>(Counts.Blackboards));
    CountsJson->SetNumberField(TEXT("blackboard_keys"), static_cast<double>(Counts.BlackboardKeys));
    CountsJson->SetNumberField(TEXT("eqs_queries"), static_cast<double>(Counts.EQSQueries));
    CountsJson->SetNumberField(TEXT("eqs_options"), static_cast<double>(Counts.EQSOptions));
    CountsJson->SetNumberField(TEXT("eqs_generators"), static_cast<double>(Counts.EQSGenerators));
    CountsJson->SetNumberField(TEXT("eqs_tests"), static_cast<double>(Counts.EQSTests));
    CountsJson->SetNumberField(TEXT("statetrees"), static_cast<double>(Counts.StateTrees));
    CountsJson->SetNumberField(TEXT("statetree_states"), static_cast<double>(Counts.StateTreeStates));
    CountsJson->SetNumberField(TEXT("statetree_nodes"), static_cast<double>(Counts.StateTreeNodes));
    CountsJson->SetNumberField(TEXT("statetree_transitions"), static_cast<double>(Counts.StateTreeTransitions));
    CountsJson->SetNumberField(TEXT("statetree_bindings"), static_cast<double>(Counts.StateTreeBindings));
    CountsJson->SetNumberField(TEXT("ai_properties"), static_cast<double>(Counts.AIProperties));
    CountsJson->SetNumberField(TEXT("pcg_graphs"), static_cast<double>(Counts.PCGGraphs));
    CountsJson->SetNumberField(TEXT("pcg_nodes"), static_cast<double>(Counts.PCGNodes));
    CountsJson->SetNumberField(TEXT("pcg_pins"), static_cast<double>(Counts.PCGPins));
    CountsJson->SetNumberField(TEXT("pcg_edges"), static_cast<double>(Counts.PCGEdges));
    CountsJson->SetNumberField(TEXT("pcg_properties"), static_cast<double>(Counts.PCGProperties));
    CountsJson->SetNumberField(TEXT("materials"), static_cast<double>(Counts.Materials));
    CountsJson->SetNumberField(TEXT("material_expressions"), static_cast<double>(Counts.MaterialExpressions));
    CountsJson->SetNumberField(TEXT("material_edges"), static_cast<double>(Counts.MaterialEdges));
    CountsJson->SetNumberField(TEXT("material_properties"), static_cast<double>(Counts.MaterialProperties));
    Manifest->SetObjectField(TEXT("counts"), CountsJson);

    if (!SaveJsonObject(FPaths::Combine(OutputDir, TEXT("manifest.json")), Manifest))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetTool: could not write manifest.json."));
        return 5;
    }

    UE_LOG(LogTemp, Display, TEXT("UnrealAssetTool: indexed %lld files, %lld assets, %lld blueprints, %lld blueprint nodes."),
        Counts.Files, Counts.Assets, Counts.Blueprints, Counts.BlueprintNodes);
    UE_LOG(LogTemp, Display, TEXT("UnrealAssetTool: AI assets: %lld behavior trees, %lld blackboards, %lld EQS queries, %lld StateTrees."),
        Counts.BehaviorTrees, Counts.Blackboards, Counts.EQSQueries, Counts.StateTrees);
    UE_LOG(LogTemp, Display, TEXT("UnrealAssetTool: visual assets: %lld PCG graphs, %lld materials/functions, %lld material expressions."),
        Counts.PCGGraphs, Counts.Materials, Counts.MaterialExpressions);
    UE_LOG(LogTemp, Display, TEXT("UnrealAssetTool: output: %s"), *OutputDir);
    return 0;
}

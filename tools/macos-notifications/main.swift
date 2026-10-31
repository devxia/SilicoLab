import Cocoa
import UserNotifications

// Only fixed privacy-safe content is sent to macOS. JSONL is private parent IPC.
let outputLock = NSLock()
func emit(_ value: [String:Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject:value, options:[.sortedKeys]) else { return }
    outputLock.lock(); defer { outputLock.unlock() }
    FileHandle.standardOutput.write(data); FileHandle.standardOutput.write(Data([10]))
}
func validTarget(_ target:[String:Any]) -> Bool {
    let expected:Set<String> = ["projectId","conversationId","taskId","decisionId"]
    guard Set(target.keys)==expected else { return false }
    for key in ["projectId","taskId","decisionId"] {
        guard let value=target[key] as? String, UUID(uuidString:value) != nil else { return false }
    }
    guard let conversation=target["conversationId"] as? String, !conversation.isEmpty, conversation.count<=30,
          conversation.allSatisfy({$0.isASCII && $0.isNumber}) else { return false }
    return true
}
class Delegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    let center=UNUserNotificationCenter.current()
    func applicationDidFinishLaunching(_ notification:Notification) {
        center.delegate=self
        emit(["event":"ready","bundleId":Bundle.main.bundleIdentifier ?? "missing"])
        DispatchQueue.global(qos:.utility).async {
            var pending=Data()
            while true {
                let bytes=FileHandle.standardInput.availableData
                if bytes.isEmpty { DispatchQueue.main.async { NSApplication.shared.terminate(nil) }; return }
                pending.append(bytes)
                if pending.count>65536 { DispatchQueue.main.async { NSApplication.shared.terminate(nil) }; return }
                while let end=pending.firstIndex(of:10) {
                    let line=Data(pending[..<end]);pending.removeSubrange(...end)
                    guard let value=(try? JSONSerialization.jsonObject(with:line)) as? [String:Any] else { continue }
                    DispatchQueue.main.async { self.handle(value) }
                }
            }
        }
    }
    func handle(_ value:[String:Any]) {
        guard let id=value["id"] as? String, let op=value["op"] as? String else { return }
        switch op {
        case "status":
            center.getNotificationSettings { settings in
                self.center.getDeliveredNotifications { delivered in
                    emit(["id":id,"authorization":settings.authorizationStatus.rawValue,"alert":settings.alertSetting.rawValue,"delivered":delivered.map{$0.request.identifier}])
                }
            }
        case "enable":
            guard value["explicitUserEnabled"] as? Bool == true else { emit(["id":id,"error":"Explicit enable required"]);return }
            center.requestAuthorization(options:[.alert]) { granted,error in
                emit(["id":id,"granted":granted,"error":error == nil ? "" : "macOS notification authorization failed"])
            }
        case "notify":
            guard let target=value["target"] as? [String:Any],validTarget(target),let decision=target["decisionId"] as? String else {emit(["id":id,"error":"Invalid target"]);return}
            let content=UNMutableNotificationContent()
            content.title="SilicoLab 需要你的决定"
            content.body="一个任务已保存待处理问题。打开原任务查看并答复；任务没有自动继续。"
            content.userInfo=target
            let request=UNNotificationRequest(identifier:"silicolab-decision-"+decision,content:content,trigger:nil)
            center.add(request) { error in emit(["id":id,"submitted":error == nil,"error":error == nil ? "" : "macOS notification submission failed"]) }
        case "remove":
            guard let ids=value["identifiers"] as? [String],ids.count<=200,ids.allSatisfy({$0.hasPrefix("silicolab-decision-") && $0.count<100}) else {emit(["id":id,"error":"Invalid identifiers"]);return}
            center.removePendingNotificationRequests(withIdentifiers:ids)
            center.removeDeliveredNotifications(withIdentifiers:ids)
            emit(["id":id,"removed":true])
        case "disable":
            center.removeAllPendingNotificationRequests();center.removeAllDeliveredNotifications();emit(["id":id,"disabled":true])
        case "close":emit(["id":id,"closed":true]);NSApplication.shared.terminate(nil)
        default:emit(["id":id,"error":"Unsupported operation"])
        }
    }
    func userNotificationCenter(_ center:UNUserNotificationCenter,willPresent notification:UNNotification,withCompletionHandler completionHandler:@escaping(UNNotificationPresentationOptions)->Void) { completionHandler([.banner,.list]) }
    func userNotificationCenter(_ center:UNUserNotificationCenter,didReceive response:UNNotificationResponse,withCompletionHandler completionHandler:@escaping()->Void) {
        if response.actionIdentifier==UNNotificationDefaultActionIdentifier,let target=response.notification.request.content.userInfo as? [String:Any],validTarget(target) { emit(["event":"selected","target":target]) }
        completionHandler()
    }
}
let app=NSApplication.shared
let delegate=Delegate()
app.delegate=delegate
app.setActivationPolicy(.accessory)
app.run()

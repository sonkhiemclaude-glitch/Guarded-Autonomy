#define main GuardedScenarioMain
#include "guarded-autonomy-manet.cc"
#undef main
void RequireProbe(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
int main(){
 nodeState.resize(2);neighborTtl=3;reciprocalProbe=true;nodeState[0].lastSeen[1]=0;
 nodeState[0].ownNonces.emplace_back(0,0x12345678);
 RequireProbe(!IsNeighbor(0,1),"one-way receipt established a reciprocal neighbor");
 std::vector<uint8_t> bytes={0,0,0x12,0x34,0x56,0x78};RequireProbe(ProbeDecode(ProbeEncode(bytes))==bytes,"probe codec roundtrip failed");
 auto message=json({{"probe_version",1},{"nonce",uint32_t(44)},{"echoes",ProbeEncode(bytes)},{"status","untrusted payload"}}).dump();
 ObserveProbe(0,1,message);RequireProbe(message=="untrusted payload","trusted envelope leaked into free text");RequireProbe(IsNeighbor(0,1),"matching fresh echo not admitted");
 nodeState[0].reciprocalSeen.clear();bytes.back()^=1;
 message=json({{"probe_version",1},{"nonce",uint32_t(44)},{"echoes",ProbeEncode(bytes)},{"status","payload"}}).dump();ObserveProbe(0,1,message);
 RequireProbe(!IsNeighbor(0,1),"wrong nonce admitted reciprocal neighbor");
 message="{\"probe_version\":\"hostile\",\"nonce\":-1}";ObserveProbe(0,1,message);
 nodeState[0].reciprocalSeen[1]=0;
 Simulator::Schedule(Seconds(4),[]{nodeState[0].lastSeen[1]=4;RequireProbe(!IsNeighbor(0,1),"new incoming packet refreshed an expired reciprocal proof");});
 Simulator::Run();Simulator::Destroy();std::cout<<"PASS: reciprocal evidence requires a matching echo, tolerates malformed metadata, and expires independently of one-way receipts"<<std::endl;
}

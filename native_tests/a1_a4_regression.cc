#include "ns3/aodv-rtable.h"
#include "ns3/simulator.h"
#include "ns3/nstime.h"
#include <iostream>
#include <stdexcept>
#include <functional>
#include <string>
using namespace ns3;
using namespace ns3::aodv;
static bool allowCommit=true;
static unsigned hookCalls=0;
static Ipv4Address dst("10.7.0.20"), oldHop("10.7.0.2"), newHop("10.7.0.3");
static Ipv4InterfaceAddress iface(Ipv4Address("10.7.0.1"),Ipv4Mask("255.255.255.0"));
void need(bool c,const char* m){if(!c)throw std::runtime_error(m);}
RoutingTableEntry entry(double life=10){return RoutingTableEntry(nullptr,dst,true,7,iface,3,oldHop,Seconds(life));}
const RoutingTableEntry& stored(const RoutingTable& t){return t.GuardEntries().at(dst);}
void setup(){RoutingTable::GuardPersistent=true;RoutingTable::GuardCloneEntries=true;RoutingTable::GuardBypass=false;allowCommit=true;hookCalls=0;RoutingTable::GuardCommit=[](RoutingTable*,RoutingTableEntry&,const RoutingTableEntry*){++hookCalls;return allowCommit;};}
int main(){
 int passed=0,failed=0;
 auto test=[&](const char* name,std::function<void()> f){setup();try{f();++passed;std::cout<<"{\"test\":\""<<name<<"\",\"passed\":true}\n";}catch(const std::exception& e){++failed;std::cout<<"{\"test\":\""<<name<<"\",\"passed\":false,\"error\":\""<<e.what()<<"\"}\n";}Simulator::Destroy();};
 test("valid_insert_reaches_hook_and_denial_preserves_empty_table",[]{RoutingTable t(Seconds(5));auto e=entry();allowCommit=false;need(!t.AddRoute(e),"rejected insert accepted");need(hookCalls==1&&t.GuardEntries().empty(),"hook or table state mismatch");});
 test("valid_update_denied_without_mutating_stored_route",[]{RoutingTable t(Seconds(5));auto e=entry();need(t.AddRoute(e),"setup insert");RoutingTableEntry c;need(t.LookupRoute(dst,c),"lookup");c.SetNextHop(newHop);c.SetSeqNo(9);allowCommit=false;need(!t.Update(c),"rejected update accepted");need(hookCalls==2&&stored(t).GetNextHop()==oldHop&&stored(t).GetSeqNo()==7,"rejected candidate mutated table");});
 test("lookup_and_insert_detach_shared_route_pointers",[]{RoutingTable t(Seconds(5));auto e=entry();need(t.AddRoute(e),"setup insert");e.SetNextHop(newHop);need(stored(t).GetNextHop()==oldHop,"insert alias");RoutingTableEntry c;need(t.LookupRoute(dst,c),"lookup");c.SetNextHop(newHop);need(stored(t).GetNextHop()==oldHop,"lookup alias");});
 test("invalidation_strictly_increments_valid_key_and_is_idempotent",[]{auto e=entry();e.Invalidate(Seconds(5));need(e.GetFlag()==INVALID&&e.GetSeqNo()==8&&e.GetHop()==3,"invalidated key");e.Invalidate(Seconds(5));need(e.GetSeqNo()==8,"repeat invalidation changed key");});
 test("delete_retains_invalid_entry_and_key",[]{RoutingTable t(Seconds(5));auto e=entry();need(t.AddRoute(e),"setup insert");need(t.DeleteRoute(dst),"delete failed");need(t.GuardEntries().size()==1&&stored(t).GetFlag()==INVALID&&stored(t).GetSeqNo()==8,"deleted retained key");});
 test("clear_retains_invalid_entry_and_key",[]{RoutingTable t(Seconds(5));auto e=entry();need(t.AddRoute(e),"setup insert");t.Clear();need(t.GuardEntries().size()==1&&stored(t).GetFlag()==INVALID&&stored(t).GetSeqNo()==8,"clear reset key");});
 test("interface_removal_retains_invalid_entry_and_key",[]{RoutingTable t(Seconds(5));auto e=entry();need(t.AddRoute(e),"setup insert");t.DeleteAllRoutesFromInterface(iface);need(t.GuardEntries().size()==1&&stored(t).GetFlag()==INVALID&&stored(t).GetSeqNo()==8,"interface removal reset key");});
 test("expiry_and_later_purge_retain_key",[]{RoutingTable t(Seconds(5));auto e=entry(1);need(t.AddRoute(e),"setup insert");Simulator::Schedule(Seconds(2),[&](){t.Purge();need(stored(t).GetFlag()==INVALID&&stored(t).GetSeqNo()==8,"expiry did not invalidate");});Simulator::Schedule(Seconds(20),[&](){t.Purge();need(t.GuardEntries().size()==1&&stored(t).GetSeqNo()==8,"purge erased invalid key");});Simulator::Run();});
 test("route_error_retains_and_increments_key",[]{RoutingTable t(Seconds(5));auto e=entry();need(t.AddRoute(e),"setup insert");t.InvalidateRoutesWithDst({{dst,7}});need(stored(t).GetFlag()==INVALID&&stored(t).GetSeqNo()==8,"route error reset key");});
 test("reactivation_is_guarded_and_denial_keeps_invalid_entry",[]{RoutingTable t(Seconds(5));auto e=entry();need(t.AddRoute(e),"setup insert");need(t.SetEntryState(dst,INVALID),"invalidate failed");allowCommit=false;need(!t.SetEntryState(dst,VALID),"reactivation bypassed hook");need(hookCalls==2&&stored(t).GetFlag()==INVALID&&stored(t).GetSeqNo()==8,"reactivation state mismatch");});
 test("nonvalid_search_update_cannot_lower_retained_key",[]{RoutingTable t(Seconds(5));auto e=entry();need(t.AddRoute(e),"setup insert");RoutingTableEntry c;need(t.LookupRoute(dst,c),"lookup");c.SetFlag(IN_SEARCH);c.SetSeqNo(1);c.SetHop(99);need(t.Update(c),"search update failed");need(stored(t).GetSeqNo()>=8&&stored(t).GetHop()==3,"search placeholder lowered key");});
 RoutingTable::GuardCommit=nullptr;
 std::cout<<"{\"summary\":true,\"passed\":"<<passed<<",\"failed\":"<<failed<<",\"scope\":\"Native routing-table API regression only; no proof of complete mediation, node reboot persistence or global loop freedom\"}\n";
 return failed?1:0;
}

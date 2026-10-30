#include "ns3/aodv-module.h"
#include "ns3/internet-module.h"
#include <iostream>
#include <stdexcept>
using namespace ns3;
void Require(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
int main(){
 aodv::RoutingTable::GuardPersistent=true;aodv::RoutingTable::GuardCloneEntries=true;
 aodv::RoutingTable table(Seconds(1));
 aodv::RoutingTableEntry original(nullptr,Ipv4Address("10.0.0.9"),true,5,
  Ipv4InterfaceAddress(Ipv4Address("10.0.0.1"),Ipv4Mask("255.255.255.0")),3,Ipv4Address("10.0.0.2"),Seconds(10));
 Require(table.AddRoute(original),"cannot initialize test entry");
 original.SetNextHop(Ipv4Address("10.0.0.8"));
 Require(table.GuardEntries().begin()->second.GetNextHop()==Ipv4Address("10.0.0.2"),"insert retained a mutable alias");
 aodv::RoutingTableEntry candidate;Require(table.LookupRoute(Ipv4Address("10.0.0.9"),candidate),"lookup failed");
 candidate.SetNextHop(Ipv4Address("10.0.0.3"));
 Require(table.GuardEntries().begin()->second.GetNextHop()==Ipv4Address("10.0.0.2"),"lookup bypassed guard through mutable alias");
 aodv::RoutingTable::GuardCommit=[](auto*,auto&,const auto*){return false;};
 Require(!table.Update(candidate),"rejecting guard did not reject");
 Require(table.GuardEntries().begin()->second.GetNextHop()==Ipv4Address("10.0.0.2"),"rejected update mutated stored next hop");
 table.DeleteRoute(Ipv4Address("10.0.0.9"));
 Require(table.GuardEntries().size()==1,"invalidation deleted persistent key");
 Require(table.GuardEntries().begin()->second.GetSeqNo()==6,"invalidation failed to increment sequence");
 Require(table.GuardEntries().begin()->second.GetHop()==3,"invalidation changed retained hop count");
 aodv::RoutingTable::GuardCommit=nullptr;Simulator::Destroy();
 std::cout<<"PASS: insert/lookup/update aliases cannot bypass hook; invalidation retains and increases key."<<std::endl;
}

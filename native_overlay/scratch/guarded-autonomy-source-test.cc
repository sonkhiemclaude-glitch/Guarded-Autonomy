#include "ns3/aodv-module.h"
#include "ns3/internet-module.h"
#include <iostream>
using namespace ns3;
int main(){
 aodv::RoutingTableEntry placeholder(nullptr,Ipv4Address("10.7.0.3"),false,0,Ipv4InterfaceAddress(),0,Ipv4Address(),Seconds(10));
 auto before=placeholder.GetRoute()->GetSource();
 placeholder.SetInterface(Ipv4InterfaceAddress(Ipv4Address("10.7.0.1"),Ipv4Mask("255.255.0.0")));
 auto after=placeholder.GetRoute()->GetSource();
 std::cout<<"before="<<before<<" after="<<after<<" expected=10.7.0.1"<<std::endl;
 if(after!=Ipv4Address("10.7.0.1")){std::cerr<<"FAIL: interface change retained an uninitialized route source"<<std::endl;return 1;}
 aodv::RoutingTable::GuardCloneEntries=true;aodv::RoutingTable table(Seconds(1));table.AddRoute(placeholder);
 aodv::RoutingTableEntry candidate;table.LookupRoute(Ipv4Address("10.7.0.3"),candidate);
 candidate.SetInterface(Ipv4InterfaceAddress(Ipv4Address("10.7.0.2"),Ipv4Mask("255.255.0.0")));
 if(table.GuardEntries().begin()->second.GetRoute()->GetSource()!=Ipv4Address("10.7.0.1"))return 2;
 std::cout<<"PASS: source follows selected interface; detached candidates preserve stored source"<<std::endl;
}

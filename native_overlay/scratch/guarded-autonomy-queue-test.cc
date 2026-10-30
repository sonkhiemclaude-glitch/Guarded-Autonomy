#include "ns3/aodv-module.h"
#include "ns3/internet-module.h"
#include "ns3/network-module.h"
#include <iostream>
#include <stdexcept>
using namespace ns3;
void Check(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
int main(){
 auto node=CreateObject<Node>();InternetStackHelper stack;stack.Install(node);
 auto dev=CreateObject<SimpleNetDevice>();node->AddDevice(dev);auto ip=node->GetObject<Ipv4>();
 auto iface=ip->AddInterface(dev);auto address=Ipv4InterfaceAddress(Ipv4Address("10.7.0.1"),Ipv4Mask("255.255.0.0"));ip->AddAddress(iface,address);ip->SetUp(iface);
 aodv::RoutingTable table(Seconds(1));aodv::RoutingTable::GuardCloneEntries=true;
 aodv::RoutingTableEntry pending(nullptr,Ipv4Address("10.7.0.3"),false,0,Ipv4InterfaceAddress(),0,Ipv4Address(),Seconds(10));pending.SetFlag(aodv::IN_SEARCH);table.AddRoute(pending);
 aodv::RoutingTableEntry answer(dev,Ipv4Address("10.7.0.3"),true,5,address,2,Ipv4Address("10.7.0.2"),Seconds(10));
 Check(aodv::RoutingProtocol::GuardCanDispatch(answer.GetRoute(),ip),"complete route was rejected");
 aodv::RoutingTable::GuardCommit=[](auto*,auto&,const auto*){return false;};Check(!table.Update(answer),"guard rejection failed");
 aodv::RoutingTableEntry stored;Check(!table.LookupValidRoute(Ipv4Address("10.7.0.3"),stored),"rejected RREP became valid");table.LookupRoute(Ipv4Address("10.7.0.3"),stored);
 Check(!aodv::RoutingProtocol::GuardCanDispatch(stored.GetRoute(),ip),"search placeholder may reach IPv4");
 answer.SetOutputDevice(CreateObject<SimpleNetDevice>());Check(!aodv::RoutingProtocol::GuardCanDispatch(answer.GetRoute(),ip),"foreign device may reach IPv4");
 aodv::RoutingTable::GuardCommit=nullptr;Simulator::Destroy();std::cout<<"PASS: rejected RREP leaves a pending route; incomplete and foreign-device routes cannot dispatch queued packets"<<std::endl;
}
